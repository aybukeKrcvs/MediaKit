# ruff: noqa: E501  (translation table: one string per line reads better than wrapped)
"""Fill empty Turkish translations in mediakit_tr.ts.

Only touches messages whose translation is empty. Anything you already
translated (or edited in Qt Linguist) is left alone, so it is safe to
run after every lupdate.

Usage (from the project root):
    uv run python tools/fill_tr.py src/mediakit/assets/i18n/mediakit_tr.ts

Filled entries stay marked "unfinished" so Qt Linguist shows them for
review; pass --finish to mark them done instead.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

TR: dict[str, str] = {
    # ---- hub / shared ----
    "SOON": "YAKINDA",
    "\u2190 All tools": "\u2190 T\u00fcm ara\u00e7lar",
    "Pick a task. Everything runs offline on this computer.": "Bir i\u015f se\u00e7in. Her \u015fey bu bilgisayarda, \u00e7evrimd\u0131\u015f\u0131 \u00e7al\u0131\u015f\u0131r.",
    "Start": "Ba\u015flat",
    "Add files": "Dosya ekle",
    "Add folder": "Klas\u00f6r ekle",
    "Select all": "T\u00fcm\u00fcn\u00fc se\u00e7",
    "Select none": "Hi\u00e7birini se\u00e7me",
    "Clear list": "Listeyi temizle",
    "Output folder...": "\u00c7\u0131kt\u0131 klas\u00f6r\u00fc...",
    "If file exists": "Dosya varsa",
    "Cancel": "\u0130ptal",
    "Keep both": "\u0130kisini de tut",
    "Overwrite": "\u00dczerine yaz",
    "Skip": "Atla",
    "Same folder as each source file": "Her dosyan\u0131n kendi klas\u00f6r\u00fc",
    "Add files to begin.": "Ba\u015flamak i\u00e7in dosya ekleyin.",
    "Click an image to edit it.": "D\u00fczenlemek i\u00e7in bir g\u00f6rsele t\u0131klay\u0131n.",
    "All files excluded.": "T\u00fcm dosyalar hari\u00e7 tutuldu.",
    "%n file(s) ready.": "%n dosya haz\u0131r.",
    "Supported files": "Desteklenen dosyalar",
    "Select files": "Dosya se\u00e7",
    "Select folder": "Klas\u00f6r se\u00e7",
    "Select output folder": "\u00c7\u0131kt\u0131 klas\u00f6r\u00fcn\u00fc se\u00e7",
    "Cancelling...": "\u0130ptal ediliyor...",
    "Processing: %1": "\u0130\u015fleniyor: %1",
    "%n done": "%n tamamland\u0131",
    "%n skipped": "%n atland\u0131",
    "%n failed": "%n ba\u015far\u0131s\u0131z",
    "cancelled": "iptal edildi",
    "Error: %1": "Hata: %1",
    "Quality": "Kalite",
    "Save": "Kaydet",
    # ---- image hub ----
    "IMAGE TOOLS": "G\u00d6RSEL ARA\u00c7LARI",
    "Convert format": "Format d\u00f6n\u00fc\u015ft\u00fcr",
    "Turn images into PNG, JPG or WebP.": "G\u00f6rselleri PNG, JPG veya WebP'ye \u00e7evirin.",
    "Resize": "Boyutland\u0131r",
    "Change dimensions by width, height or percent.": "Boyutu geni\u015flik, y\u00fckseklik veya y\u00fczdeyle de\u011fi\u015ftirin.",
    "Crop & rotate": "K\u0131rp ve d\u00f6nd\u00fcr",
    "Crop by hand or to a fixed ratio, rotate 90\u00b0.": "Elle veya sabit oranda k\u0131rp\u0131n, 90\u00b0 d\u00f6nd\u00fcr\u00fcn.",
    "Compress": "S\u0131k\u0131\u015ft\u0131r",
    "Smaller files, same size and format.": "Daha k\u00fc\u00e7\u00fck dosya, ayn\u0131 boyut ve format.",
    "Remove metadata": "Meta veriyi kald\u0131r",
    "Strip location, camera and date info (EXIF).": "Konum, kamera ve tarih bilgisini (EXIF) silin.",
    "Watermark": "Filigran",
    "Stamp text or a logo on your images.": "G\u00f6rsellere metin veya logo bas\u0131n.",
    "Remove background": "Arka plan\u0131 kald\u0131r",
    "Cut out the subject with an AI model.": "Konuyu bir AI modeliyle kesip \u00e7\u0131kar\u0131n.",
    "Upscale": "B\u00fcy\u00fct",
    "Enlarge images with AI super-resolution.": "G\u00f6rselleri AI super-resolution ile b\u00fcy\u00fct\u00fcn.",
    # ---- convert ----
    "Convert to": "Hedef format",
    "Lossless": "Kay\u0131ps\u0131z",
    "Lossless, keeps transparency. Larger files.": "Kay\u0131ps\u0131z, \u015feffafl\u0131\u011f\u0131 korur. Dosyalar b\u00fcy\u00fck.",
    "Photos": "Foto\u011fraf",
    "Small files for photos. No transparency.": "Foto\u011fraflar i\u00e7in k\u00fc\u00e7\u00fck dosya. \u015eeffafl\u0131k yok.",
    "Smallest": "En k\u00fc\u00e7\u00fck",
    "Modern format, smallest files, keeps transparency.": "Modern format, en k\u00fc\u00e7\u00fck dosyalar, \u015feffafl\u0131\u011f\u0131 korur.",
    "Convert": "D\u00f6n\u00fc\u015ft\u00fcr",
    # ---- resize ----
    "Resize by": "Boyutland\u0131rma \u015fekli",
    "Width": "Geni\u015flik",
    "Max width": "Maks. geni\u015flik",
    "Limit the width. Height follows the aspect ratio.": "Geni\u015fli\u011fi s\u0131n\u0131rlar. Y\u00fckseklik orana g\u00f6re ayarlan\u0131r.",
    "Height": "Y\u00fckseklik",
    "Max height": "Maks. y\u00fckseklik",
    "Limit the height. Width follows the aspect ratio.": "Y\u00fcksekli\u011fi s\u0131n\u0131rlar. Geni\u015flik orana g\u00f6re ayarlan\u0131r.",
    "Fit": "S\u0131\u011fd\u0131r",
    "Inside a box": "Kutunun i\u00e7ine",
    "Shrink until the image fits inside width x height.": "G\u00f6rsel geni\u015flik x y\u00fckseklik kutusuna s\u0131\u011fana kadar k\u00fc\u00e7\u00fcl\u00fcr.",
    "Percent": "Y\u00fczde",
    "Scale": "\u00d6l\u00e7ek",
    "Scale both sides by a percentage.": "\u0130ki kenar\u0131 da y\u00fczdeyle \u00f6l\u00e7ekler.",
    "Allow enlarging small images": "K\u00fc\u00e7\u00fck g\u00f6rselleri b\u00fcy\u00fctmeye izin ver",
    # ---- compress ----
    "Compression level": "S\u0131k\u0131\u015ft\u0131rma seviyesi",
    "Light": "Hafif",
    "Barely visible change.": "Fark neredeyse g\u00f6r\u00fcnmez.",
    "Balanced": "Dengeli",
    "Good size/quality trade-off.": "Boyut ve kalite aras\u0131nda iyi denge.",
    "Strong": "G\u00fc\u00e7l\u00fc",
    "Smallest files, visible artefacts.": "En k\u00fc\u00e7\u00fck dosyalar, g\u00f6r\u00fcn\u00fcr bozulmalar.",
    "PNG is lossless: PNG files are only re-optimised, so savings are small. "
    "Convert them to WebP for real size reductions.": "PNG kay\u0131ps\u0131zd\u0131r: PNG dosyalar sadece yeniden optimize edilir, kazan\u00e7 k\u00fc\u00e7\u00fckt\u00fcr. "
    "Ger\u00e7ek k\u00fc\u00e7\u00fclme i\u00e7in WebP'ye d\u00f6n\u00fc\u015ft\u00fcr\u00fcn.",
    # ---- crop & rotate ----
    "Square": "Kare",
    "Square, e.g. an Instagram post": "Kare, \u00f6rn. Instagram g\u00f6nderisi",
    "Classic": "Klasik",
    "Classic photo / SD screen": "Klasik foto\u011fraf / SD ekran",
    "Portrait": "Dikey",
    "Classic photo, portrait": "Klasik foto\u011fraf, dikey",
    "Wide": "Geni\u015f",
    "Widescreen / HD video": "Geni\u015f ekran / HD video",
    "Stories": "Hikaye",
    "Vertical: Stories & Reels": "Dikey: Hikayeler ve Reels",
    "Ultrawide": "Ultra geni\u015f",
    "Ultra-widescreen / cinema": "Ultra geni\u015f ekran / sinema",
    "Ultra-tall": "Ultra uzun",
    "Ultra-tall vertical": "Ultra uzun dikey",
    "Single image": "Tek g\u00f6rsel",
    "Draw the crop by hand on one image.": "Tek bir g\u00f6rselde k\u0131rpma alan\u0131n\u0131 elle \u00e7izin.",
    "Batch": "Toplu",
    "Crop many images to the same ratio, centred.": "\u00c7ok say\u0131da g\u00f6rseli ayn\u0131 oranda, ortalayarak k\u0131rp\u0131n.",
    "Rotate": "D\u00f6nd\u00fcr",
    "Rotate 90\u00b0 left": "90\u00b0 sola d\u00f6nd\u00fcr",
    "Rotate 90\u00b0 right": "90\u00b0 sa\u011fa d\u00f6nd\u00fcr",
    "Aspect ratio": "En-boy oran\u0131",
    "Reset crop": "K\u0131rpmay\u0131 s\u0131f\u0131rla",
    "Crop every image to": "T\u00fcm g\u00f6rselleri \u015fu orana k\u0131rp",
    "Each image keeps its centre; the edges that don't fit the ratio are trimmed.": "Her g\u00f6rselin merkezi korunur, orana s\u0131\u011fmayan kenarlar k\u0131rp\u0131l\u0131r.",
    "Free": "Serbest",
    "Any shape": "Herhangi bir \u015fekil",
    "No fixed ratio": "Sabit oran yok",
    "Original": "Orijinal",
    "No crop": "K\u0131rpma yok",
    "Only rotate, don't crop": "Sadece d\u00f6nd\u00fcr, k\u0131rpma",
    # ---- audio hub ----
    "AUDIO & SPEECH": "SES VE KONU\u015eMA",
    "Convert audio": "Ses d\u00f6n\u00fc\u015ft\u00fcr",
    "MP3, WAV, FLAC, OGG, M4A and more.": "MP3, WAV, FLAC, OGG, M4A ve daha fazlas\u0131.",
    "Speech to text": "Konu\u015fmadan metne",
    "Transcribe recordings, export SRT/VTT subtitles.": "Kay\u0131tlar\u0131 metne d\u00f6k\u00fcn, SRT/VTT altyaz\u0131 al\u0131n.",
    "Reduce noise": "G\u00fcr\u00fclt\u00fc azalt",
    "Clean up hiss and background noise.": "C\u0131z\u0131rt\u0131 ve arka plan g\u00fcr\u00fclt\u00fcs\u00fcn\u00fc temizleyin.",
    "Text to speech": "Metinden sese",
    "Read text aloud in Turkish or English.": "Metni T\u00fcrk\u00e7e veya \u0130ngilizce seslendirin.",
    "Record & transcribe": "Kaydet ve metne d\u00f6k",
    "Record from the microphone, then transcribe.": "Mikrofondan kaydedin, sonra metne d\u00f6k\u00fcn.",
    # ---- pdf hub ----
    "PDF TOOLS": "PDF ARA\u00c7LARI",
    "Merge PDF": "PDF birle\u015ftir",
    "Combine several PDFs in the order you choose.": "Birden fazla PDF'i istedi\u011finiz s\u0131rayla birle\u015ftirin.",
    "Split PDF": "PDF b\u00f6l",
    "Extract pages or ranges into separate files.": "Sayfalar\u0131 veya aral\u0131klar\u0131 ayr\u0131 dosyalara ay\u0131r\u0131n.",
    "Organize pages": "Sayfalar\u0131 d\u00fczenle",
    "Rotate, reorder or delete pages.": "Sayfalar\u0131 d\u00f6nd\u00fcr\u00fcn, s\u0131ralay\u0131n veya silin.",
    "Compress PDF": "PDF s\u0131k\u0131\u015ft\u0131r",
    "Reduce file size for sharing.": "Payla\u015fmak i\u00e7in dosya boyutunu k\u00fc\u00e7\u00fclt\u00fcn.",
    "Convert from PDF": "PDF'ten d\u00f6n\u00fc\u015ft\u00fcr",
    "PDF to images, text, Markdown, Word or Excel.": "PDF'ten g\u00f6rsel, metin, Markdown, Word veya Excel.",
    "Convert to PDF": "PDF'e d\u00f6n\u00fc\u015ft\u00fcr",
    "Images, Markdown, HTML or Office files to PDF.": "G\u00f6rsel, Markdown, HTML veya Office dosyalar\u0131ndan PDF.",
    "Watermark & page numbers": "Filigran ve sayfa numaras\u0131",
    "Stamp text, a logo or page numbers.": "Metin, logo veya sayfa numaras\u0131 bas\u0131n.",
    "Protect & clean": "Koru ve temizle",
    "Add or remove a password, strip metadata.": "\u015eifre ekleyin veya kald\u0131r\u0131n, meta veriyi silin.",
    # ---- 1c: remove metadata ----
    "Found in the selected file": "Seçili dosyada bulunanlar",
    "Keep colour profile (ICC)": "Renk profilini koru (ICC)",
    "A colour profile holds no personal data; removing it can shift colours.": "Renk profili kişisel veri içermez; silmek renkleri kaydırabilir.",
    "JPEG, PNG and WebP are cleaned without re-encoding: no quality loss. Photo orientation is kept so images don't turn sideways.": "JPEG, PNG ve WebP yeniden sıkıştırılmadan temizlenir: kalite kaybı yok. Fotoğraf yönü korunur, görseller yan yatmaz.",
    "Click an image to see what it contains.": "İçinde ne olduğunu görmek için bir görsele tıklayın.",
    "Could not read: %1": "Okunamadı: %1",
    "\u26a0 GPS location: where the photo was taken": "\u26a0 GPS konumu: fotoğrafın çekildiği yer",
    "Camera: %1": "Kamera: %1",
    "Date taken: %1": "Çekim tarihi: %1",
    "Software: %1": "Yazılım: %1",
    "XMP data (editing history, author)": "XMP verisi (düzenleme geçmişi, yazar)",
    "IPTC data (captions, copyright, keywords)": "IPTC verisi (açıklama, telif, anahtar kelimeler)",
    "Embedded comment": "Gömülü yorum",
    "Other fields: %1": "Diğer alanlar: %1",
    "No personal metadata found.": "Kişisel meta veri bulunamadı.",
    "Colour profile (ICC)": "Renk profili (ICC)",
    # ---- 1c: watermark ----
    "Text": "Metin",
    "Logo": "Logo",
    "\u00a9 Your name": "\u00a9 Adınız",
    "Colour": "Renk",
    "Choose logo...": "Logo seç...",
    "Choose logo": "Logo seç",
    "PNG with transparency works best": "En iyi sonuç şeffaf PNG ile alınır",
    "Position": "Konum",
    "Size": "Boyut",
    "Opacity": "Opaklık",
    "Top left": "Sol üst",
    "Top": "Üst",
    "Top right": "Sağ üst",
    "Left": "Sol",
    "Centre": "Orta",
    "Right": "Sağ",
    "Bottom left": "Sol alt",
    "Bottom": "Alt",
    "Bottom right": "Sağ alt",
    "Tiled across the image": "Görselin tamamına döşenmiş",
    "Add watermark": "Filigran ekle",
    "Watermark colour": "Filigran rengi",
    "Images": "Görseller",
    "Preview": "Önizleme",
    "No preview": "Önizleme yok",
    # ---- 1d: remove background ----
    "Model": "Model",
    "New background": "Yeni arka plan",
    "Fast": "Hızlı",
    "Quick, softer edges.": "Hızlı, kenarlar daha yumuşak.",
    "Standard": "Standart",
    "Cleaner edges, a few seconds per image.": "Daha temiz kenarlar, görsel başına birkaç saniye.",
    "None": "Yok",
    "Transparent PNG": "Şeffaf PNG",
    "White": "Beyaz",
    "White background, saved as JPG": "Beyaz arka plan, JPG olarak kaydedilir",
    "Any colour, saved as JPG": "İstediğiniz renk, JPG olarak kaydedilir",
    "Pick colour...": "Renk seç...",
    "Crop to the subject": "Konuya göre kırp",
    "Preview selected image": "Seçili görseli önizle",
    "Runs on: %1": "Çalıştığı yer: %1",
    "Download (%1 MB)": "İndir (%1 MB)",
    "Downloading...": "İndiriliyor...",
    "\u2713 Model installed, works offline": "\u2713 Model kurulu, çevrimdışı çalışır",
    "Needs a one-time download.": "Bir kerelik indirme gerekiyor.",
    "Download cancelled.": "İndirme iptal edildi.",
    "Download failed: %1": "İndirme başarısız: %1",
    "Model ready.": "Model hazır.",
    "Background colour": "Arka plan rengi",
    "Working...": "Çalışıyor...",
    "Preview failed: %1": "Önizleme başarısız: %1",
    # ---- 1e: upscale ----
    "Small model, seconds per image. Good for most photos.": "Küçük model, görsel başına saniyeler. Çoğu fotoğraf için yeterli.",
    "Sharper detail. Much slower, best on a GPU.": "Daha keskin detay. Çok daha yavaş, en iyisi GPU'da.",
    "Enlarge": "Büyütme",
    "Twice the width and height": "Genişlik ve yüksekliğin iki katı",
    "Four times the width and height": "Genişlik ve yüksekliğin dört katı",
    "No GPU found: large images can take minutes each on the CPU.": "GPU bulunamadı: büyük görseller CPU'da tanesi dakikalar sürebilir.",
    "Plain resize": "Normal büyütme",
    "AI upscale": "AI ile büyütme",
    "%1: %2 \u00d7 %3 px \u2192 %4 \u00d7 %5 px": "%1: %2 \u00d7 %3 px \u2192 %4 \u00d7 %5 px",
    "Too large for this scale, it will be skipped as an error.": "Bu ölçek için fazla büyük, hata olarak atlanacak.",
}


def fill(path: str, finish: bool) -> None:
    tree = ET.parse(path)
    filled = missing = 0
    for message in tree.getroot().iter("message"):
        source = message.findtext("source") or ""
        translation = message.find("translation")
        if translation is None:
            continue
        forms = translation.findall("numerusform")
        already = (
            any((f.text or "").strip() for f in forms)
            if forms
            else (translation.text or "").strip()
        )
        if already:
            continue
        turkish = TR.get(source)
        if turkish is None:
            missing += 1
            print(f"  no entry: {source!r}")
            continue
        if forms:
            for form in forms:
                form.text = turkish
        elif message.get("numerus") == "yes":
            ET.SubElement(translation, "numerusform").text = turkish
        else:
            translation.text = turkish
        if finish:
            translation.attrib.pop("type", None)
        filled += 1
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"filled {filled}, still empty {missing}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    fill(sys.argv[1], finish="--finish" in sys.argv)
