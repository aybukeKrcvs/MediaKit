"""Every downloadable model in the app, found automatically.

Any module under mediakit.modules that defines a module-level MODELS
dict is picked up, whether its values are ModelSpec objects or wrappers
with a `.spec` (UpscaleModel, BackgroundModel). A new tool therefore
cannot add a model that the About page and the license test miss.
"""

from __future__ import annotations

import importlib
import pkgutil

import mediakit.modules
from mediakit.core.models import ModelSpec


def all_model_specs() -> list[ModelSpec]:
    found: dict[str, ModelSpec] = {}
    for info in pkgutil.walk_packages(mediakit.modules.__path__, "mediakit.modules."):
        module = importlib.import_module(info.name)
        registry = getattr(module, "MODELS", None)
        if not isinstance(registry, dict):
            continue
        for entry in registry.values():
            spec = entry if isinstance(entry, ModelSpec) else getattr(entry, "spec", None)
            if isinstance(spec, ModelSpec):
                found.setdefault(spec.key, spec)
    return sorted(found.values(), key=lambda spec: spec.credit.name.lower())
