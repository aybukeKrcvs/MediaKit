"""Rebuild the Real-ESRGAN upscalers as ONNX files, without PyTorch.

Dev-only tool. The app never imports this. Usage (project root):

    uv run --with onnx python tools/export_upscalers.py <weights_dir> <out_dir>

<weights_dir> must hold the official checkpoints (BSD-3-Clause):
    RealESRGAN_x4plus.pth        github.com/xinntao/Real-ESRGAN releases v0.1.0
    realesr-general-x4v3.pth     github.com/xinntao/Real-ESRGAN releases v0.2.5.0

Instead of tracing a PyTorch model (torch.onnx.export) we write the
network graph by hand with onnx.helper and fill it with the weights read
by tools/pth_reader.py. Both networks are plain stacks of 3x3 convs, so
the graph is short, and it saves a ~2 GB torch install.

Input:  "input",  float32 [1, 3, H, W], RGB in 0..1, any H and W
Output: "output", float32 [1, 3, 4H, 4W], RGB, clipped to 0..1
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

sys.path.insert(0, str(Path(__file__).parent))
from pth_reader import load_state_dict  # noqa: E402

OPSET = 17


class GraphBuilder:
    def __init__(self, weights: dict[str, np.ndarray]) -> None:
        self.w = weights
        self.nodes: list[onnx.NodeProto] = []
        self.inits: list[onnx.TensorProto] = []
        self._n = 0

    def _name(self, hint: str) -> str:
        self._n += 1
        return f"{hint}_{self._n}"

    def const(self, value: np.ndarray, hint: str = "c") -> str:
        name = self._name(hint)
        self.inits.append(numpy_helper.from_array(value, name))
        return name

    def op(self, op_type: str, inputs: list[str], hint: str | None = None, **attrs) -> str:
        out = self._name(hint or op_type.lower())
        self.nodes.append(helper.make_node(op_type, inputs, [out], **attrs))
        return out

    def conv(self, x: str, key: str) -> str:
        weight = self.const(self.w[f"{key}.weight"], key + ".w")
        bias = self.const(self.w[f"{key}.bias"], key + ".b")
        return self.op("Conv", [x, weight, bias], key, pads=[1, 1, 1, 1], kernel_shape=[3, 3])

    def lrelu(self, x: str) -> str:
        return self.op("LeakyRelu", [x], alpha=0.2)

    def prelu(self, x: str, key: str) -> str:
        slope = self.w[f"{key}.weight"].reshape(-1, 1, 1)
        return self.op("PRelu", [x, self.const(slope, key + ".slope")])

    def scale_add(self, x: str, factor: float, residual: str) -> str:
        scaled = self.op("Mul", [x, self.const(np.array(factor, np.float32))])
        return self.op("Add", [scaled, residual])

    def upsample_nearest(self, x: str, factor: int) -> str:
        scales = self.const(np.array([1, 1, factor, factor], np.float32), "scales")
        return self.op(
            "Resize",
            [x, "", scales],
            mode="nearest",
            coordinate_transformation_mode="asymmetric",
            nearest_mode="floor",
        )

    def finish(self, x: str, name: str) -> onnx.ModelProto:
        low = self.const(np.array(0.0, np.float32))
        high = self.const(np.array(1.0, np.float32))
        self.nodes.append(helper.make_node("Clip", [x, low, high], ["output"]))
        graph = helper.make_graph(
            self.nodes,
            name,
            [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, "h", "w"])],
            [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, "H", "W"])],
            self.inits,
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", OPSET)])
        model.ir_version = 8  # readable by every onnxruntime >= 1.10
        model.producer_name = "mediakit/tools/export_upscalers.py"
        onnx.checker.check_model(model)
        return model


def build_rrdbnet(weights: dict[str, np.ndarray], blocks: int = 23) -> onnx.ModelProto:
    """RRDBNet (ESRGAN generator), x4: 23 residual-in-residual dense blocks."""
    g = GraphBuilder(weights)

    def dense_block(x: str, key: str) -> str:
        feats = [x]
        for i in range(1, 5):
            joined = feats[0] if len(feats) == 1 else g.op("Concat", feats, axis=1)
            feats.append(g.lrelu(g.conv(joined, f"{key}.conv{i}")))
        x5 = g.conv(g.op("Concat", feats, axis=1), f"{key}.conv5")
        return g.scale_add(x5, 0.2, x)

    feat = g.conv("input", "conv_first")
    body = feat
    for b in range(blocks):
        rrdb_in = body
        for r in (1, 2, 3):
            body = dense_block(body, f"body.{b}.rdb{r}")
        body = g.scale_add(body, 0.2, rrdb_in)
    feat = g.op("Add", [feat, g.conv(body, "conv_body")])
    feat = g.lrelu(g.conv(g.upsample_nearest(feat, 2), "conv_up1"))
    feat = g.lrelu(g.conv(g.upsample_nearest(feat, 2), "conv_up2"))
    out = g.conv(g.lrelu(g.conv(feat, "conv_hr")), "conv_last")
    return g.finish(out, "RealESRGAN_x4plus")


def build_srvgg(weights: dict[str, np.ndarray], convs: int = 32, scale: int = 4) -> onnx.ModelProto:
    """SRVGGNetCompact: conv/PReLU stack at low resolution, then pixel
    shuffle, plus a nearest-upsampled copy of the input as a shortcut."""
    g = GraphBuilder(weights)
    x = g.prelu(g.conv("input", "body.0"), "body.1")
    for i in range(convs):
        x = g.prelu(g.conv(x, f"body.{2 + 2 * i}"), f"body.{3 + 2 * i}")
    x = g.conv(x, f"body.{2 + 2 * convs}")
    # PyTorch PixelShuffle == ONNX DepthToSpace in "CRD" order.
    x = g.op("DepthToSpace", [x], blocksize=scale, mode="CRD")
    out = g.op("Add", [x, g.upsample_nearest("input", scale)])
    return g.finish(out, "realesr-general-x4v3")


EXPORTS = (
    ("RealESRGAN_x4plus.pth", "params_ema", build_rrdbnet, "realesrgan-x4plus.onnx"),
    ("realesr-general-x4v3.pth", "params", build_srvgg, "realesr-general-x4v3.onnx"),
)


def main(weights_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for source, key, build, target in EXPORTS:
        weights = load_state_dict(weights_dir / source)[key]
        path = out_dir / target
        onnx.save(build(weights), path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{target}\n  size   {path.stat().st_size}\n  sha256 {digest}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
