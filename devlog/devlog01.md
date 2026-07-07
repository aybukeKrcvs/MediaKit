---
date: 2026-07-07
categories:
  - Phase 0
  - Motivasyon
tags:
  - başlangıç
  - neden
---

# Neden kendi medya araç setimi yazıyorum?

Bilgisayar mühendisliği okuyorum ve son bir yıldır fark ettiğim bir şey var: sürekli küçük medya işleri yapmam gerekiyor ama elimde düzgün bir araç yok.

Bir ses kaydını `mp3`'e çevirmem lazım. Bir hocanın sesli anlatımını yazıya dökmem lazım. İki PDF'i birleştirmem, bir görseli küçültmem, telefondan çektiğim fotoğrafın çözünürlüğünü artırmam lazım. Her seferinde aynı şey oluyor: Google'a "wav to mp3 online" yazıyorum, çıkan rastgele bir siteye dosyamı **yüklüyorum**, üç reklam kapatıyorum, "ücretsiz sürümde en fazla 2 dosya" duvarına toslıyorum, ve dosyam kim bilir hangi sunucuda kim bilir ne kadar duruyor.

Bir noktada durdum ve düşündüm: bunların hepsini **kendi bilgisayarımda, offline**, tek bir yerde yapan bir şey yazsam? Hem bu dertten kurtulurum, hem de asıl önemlisi — her birinin **arka planda nasıl çalıştığını** öğrenirim.

İşte `mediakit` bu.

<!-- more -->

## Ne yapacak?

Kısaca: tek bir **masaüstü uygulaması**. Web değil, cloud değil — tamamen benim (ve arkadaşlarımın) makinesinde çalışacak. Üç ana modül var:

- **Image tools** — format dönüşümü, resize, compress, background remover, upscale
- **Audio & speech** — ses formatları, gürültü azaltma, ve en heyecanlandığım kısım: **speech-to-text** (Whisper ile) ve text-to-speech
- **PDF tools** — birleştir, böl, dönüştür, şifrele, metadata temizle

Altlarında da ortak bir **shared core** var: dosya bütünlüğü (hash), batch işleme, threading gibi hepsinin paylaştığı şeyler.

## Neden "local / offline" bu kadar önemli?

Üç sebep:

1. **Gizlilik.** Ses kayıtlarım, belgelerim, fotoğraflarım tanımadığım bir sunucuya gitmesin. Kendi diskimde kalsın.
2. **İnternetsiz çalışsın.** Otobüste, internetin çektiği çekmediği bir yerde de işimi görsün.
3. **Daha iyi bir öğrenme projesi.** Bir API'ye istek atıp cevabı göstermek kolay. Ama "sesi nasıl metne çeviriyoruz" sorusunun cevabını başkasının sunucusuna havale edersem hiçbir şey öğrenmem. Local olması beni işin **gerçeğini** anlamaya zorluyor.

## Asıl amaç: çalışan kod değil, *anlamak*

Şunu baştan itiraf edeyim: bu proje benim için "bir sürü library'yi birbirine yapıştır, çalışınca bırak" projesi değil. "Introduction to Scientific Computing" dersini aldım, signal ve image processing'e biraz altyapım var, ve gerçekten şunları **anlamak** istiyorum:

- Whisper sesi metne nasıl çeviriyor?
- Super-resolution olmayan pikselleri nasıl "uyduruyor"?
- Bir Python uygulaması nasıl tek bir `setup.exe`'ye dönüşüyor?
- Bir uygulama dili nasıl restart olmadan anında değiştiriyor?

Çalışan kodu yazmak işin kolay kısmı. Benim derdim **neden** ve **nasıl** çalıştığı.

## Şimdiye kadar öğrendiklerim (Phase 0)

Daha tek bir "feature" bile yazmadım ama Phase 0'da (temeli atma aşaması) şaşırtıcı derecede çok şey öğrendim:

**Lisanslar teknik karar değiştirebiliyormuş.** GUI framework seçerken PyQt6 vs PySide6'ya baktım. İkisi de aynı Qt'yi sarıyor ama PyQt6 **GPL** — yani onu kullansam tüm uygulamam GPL olmak zorunda kalırdı. PySide6 ise **LGPL**, daha serbest. Hayatımda ilk kez bir lisans, hangi kütüphaneyi seçeceğimi belirledi. Bunu bilmiyordum.

**Modern tooling gerçekten fark yaratıyor.** Environment yönetimi için `uv`'yi seçtim (klasik `venv`+`pip` yerine). Çok hızlı, ve `pip` dosyalarını da okuduğu için ileride vazgeçmek istesem kilitli kalmıyorum. Bu arada tam ben seçtikten sonra `uv`'nin yapımcısı OpenAI tarafından satın alındı — "bağımlı olduğum araçların geleceği" diye bir şeyi ilk kez düşündüm.

**"Sonra eklerim" = "hiç eklemem."** i18n (TR/EN dil desteği) ve light/dark theme'i **ilk günden** kurdum. Herkes "önce çalıştır, dil desteğini sonra eklersin" der ama sonradan her string'i tek tek çeviri sistemine sokmak tam bir kâbusmuş. Baştan yapınca bedava geldi.

**Görünüm için bir kimlik seçtim.** Uygulamaya eski **amber CRT monitör** estetiği verdim — siyah zemin, amber accent, monospace font. Sevdiğim birkaç siteden ilham aldım ama onları körü körüne kopyalamak yerine bir *araca* uyarladım (gösterişli bir landing page'e değil, günde yarım saat kullanacağım bir tool'a).

**Packaging'i en başta kanıtladım.** Daha uygulama bomboşken PyInstaller + Inno Setup ile gerçek bir `setup.exe` ürettim. Sebep: "benim makinemde çalışıyor ama kurulunca açılmıyor" klasik bir tuzak, ve bu tuzağı ağır ML kütüphanelerini eklemeden **önce** yakalamak istedim.

## Plan

Sırayı bilinçli seçtim: **önce image tools.** Çünkü zorluk rampası yumuşak — basit format dönüşümüyle başlıyorum, sonra ilk makine öğrenmesi modeline (background remover) geçiyorum, en sonda GPU gerektiren upscale'e. Audio (en merak ettiğim kısım, Whisper!) ikinci, PDF üçüncü sırada.

Acelem yok. Haftada 6-10 saat. Yavaş, adım adım, bir parça bitmeden diğerine geçmeden. Uzun sürecek ve bu sorun değil — amaç zaten yolculuk.

## Son bir dürüst not

Bu devlog'u iki sebeple yazıyorum. Birincisi, kendimi dürüst tutmak için — yazınca ne yaptığımı gerçekten anlayıp anlamadığımı görüyorum. İkincisi, bir şeyi **anlatmak**, onu anladığımı test etmenin en iyi yolu; bir konuyu düzgün anlatamıyorsam aslında anlamamışımdır.

Yani buradaki yazılarda bir şey saçmaysa ya da naifse, muhtemelen öyledir — öğreniyorum. Bir sonraki yazı: ilk gerçek modül, **image tools**.

Kaldığım yerden devam.
