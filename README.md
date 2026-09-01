# TYMM Soru Kontrol Merkezi — v0.6.47

Bu sürüm, v0.6.38'in çalışan şablonlu Word/PDF rapor yapısını zorunlu GitHub V7 ve ders kaynağı dağıtımıyla birleştirir. Yerel web arayüzü, Word/PDF raporuyla aynı OGM logosunu ve kurumsal renk hiyerarşisini kullanır; üstte V7'nin son uygulanan güncelleme tarihini gösterir. Başlık: **Türkiye Yüzyılı Maarif Modeli — Bağlam Temelli Çoktan Seçmeli Soru Kontrol Modülü**. Birim: **Öğretim Materyalleri ve İçerik Geliştirme Daire Başkanlığı**. Öğretmenin kendi Windows bilgisayarında yalnızca `127.0.0.1` üzerinde çalışır. Google parolası uygulamaya girmez; Gmail giriş penceresi NotebookLM sağlayıcısının tarayıcı akışıyla açılır. Gerçek NotebookLM bağımlılığı isteğe bağlıdır; otomatik testler sahte sağlayıcıyla çalışır.

## Render / canlı sunucu Gmail bağlantısı

Canlı sunucu, ziyaretçinin bilgisayarında yeni Gmail sekmesi açamaz. `notebooklm login` komutu tarayıcıyı komutun çalıştığı makinede açtığı için yerelde çalışan giriş düğmesi Render konteynerinde kullanılamaz. Sunucu sürümü bunun yerine önceden oluşturulmuş tek bir NotebookLM oturumunu Render gizli ortam değişkeninden okur.

1. Bu uygulama için kişisel hesabınız yerine ayrı ve yalnızca bu işe ayrılmış bir Google hesabı kullanın.
2. Ekranı olan yerel bilgisayarda `notebooklm login` ile o hesaba giriş yapın. Oturum dosyası varsayılan olarak `%USERPROFILE%\.notebooklm\profiles\default\storage_state.json` konumuna yazılır. Bu kurulumda kullanılacak hazır dosya `outputs\storage_state.json` konumundadır.
3. Render Dashboard'da servis için **Environment** → **Secret Files** → **Add Secret File** seçin. Dosya adını tam olarak `storage_state.json` yapın ve hazır JSON dosyasının içeriğini **Contents** alanına yapıştırın. Dosyayı Git'e, Docker imajına veya normal ortam değişkenine eklemeyin.
4. `render.yaml`, uygulamayı `/etc/secrets/storage_state.json` yoluna bakacak şekilde ayarlar. **Save, rebuild, and deploy** ile yeniden dağıtın. Secret File mevcut servise Dashboard üzerinden elle eklenmelidir.
5. Uygulamada **Bağlantıyı doğrula** düğmesine basın. Bu işlem yeni sekme açmaz; sunucudaki gizli oturumu test eder.

Oturum süresi dolarsa yerelde tekrar `notebooklm login` çalıştırıp Render'daki aynı gizli dosyayı güncelleyin. `storage_state.json`, Google oturum çerezleri içerir ve parola gibi korunmalıdır. Alternatif olarak `NOTEBOOKLM_AUTH_JSON` gizli ortam değişkeni de desteklenmeye devam eder. Bu uygulama şu anda tek sunucu hesabı kullanır; her ziyaretçinin kendi Gmail hesabıyla giriş yapacağı çok kullanıcılı OAuth akışı `notebooklm-py` tarafından sağlanmaz.

Render web servisi varsayılan olarak internete açıktır. Sunucu hesabının başkaları tarafından kullanılmasını ve yüklenen belgelerin yetkisiz işlenmesini önlemek için canlı adresi kurum erişim katmanı ya da uygulama düzeyi kimlik doğrulaması arkasına alın.

## Kurulum ve çalıştırma

PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\start.ps1
```

Sunucu PowerShell penceresi kapatıldıktan sonra da kalmışsa, yalnızca bu projenin yerel sunucusunu durdurmak için aynı klasörde `.\stop.ps1` çalıştırın. Port başka bir uygulama tarafından kullanılıyorsa betik PID'yi gösterir ve yanlışlıkla kapatmaz; eski soru-kontrol süreci olduğundan eminseniz `.\stop.ps1 -Force` kullanın. Ardından `.\start.ps1` ile yeniden başlatın.

## Öğretmenlere dağıtım

Öğretmenlerin Python veya paket kurulumuyla uğraşmaması için proje klasöründe şu komutu bir kez çalıştırın:

```powershell
.\make_teacher_package.ps1
```

Varsayılan öğretmen paketi public GitHub'daki `soru_kontrol_V7.md` dosyasını her açılışta zorunlu olarak kontrol eder. Başka bir kaynak gerektiğinde `-RulesUrl "https://.../soru_kontrol_V7.md"` kullanabilir; daha güçlü bütünlük doğrulaması için `-RulesManifestUrl "https://kurumunuz.example/tymm/manifest.json"` biçimindeki yayın paketini seçebilirsiniz.

Ders kaynakları da öğretmen ZIP’ine kopyalanmaz. `config.json` içindeki `subject_sources` alanı her ders için GitHub’ın ham HTTPS adresini gösterir; örneğin `https://raw.githubusercontent.com/ersenaktas/tymm-v6-kurallari/main/mdler/biyoloji.md`. Bu nedenle GitHub deposunda `mdler/biyoloji.md`, `mdler/fizik.md`, `mdler/kimya.md`, `mdler/matematik.md`, `mdler/cografya.md`, `mdler/tarih.md`, `mdler/felsefe.md` ve `mdler/edebiyat.md` dosyalarını bulundurmanız gerekir. Öğretmen değerlendirmeyi başlattığında yalnızca seçilen ders kaynağı HTTPS üzerinden alınır; NotebookLM’e eklendikten sonra geçici yerel kopya silinir. Ders kaynağı indirilemezse o değerlendirme başlatılmaz.

`outputs\teacher-package.zip` dosyasını gönderin. Öğretmen ZIP’i çıkarıp içindeki `Baslat.bat` dosyasına çift tıklar. Betik önce mevcut Python’u arar; yoksa Windows `winget` üzerinden kullanıcı hesabına Python 3.13 kurmayı dener, gerekirse resmi python.org yükleyicisini SHA-256 doğrulamasıyla indirir. Ardından sanal ortamı ve `notebooklm-py`/rapor bağımlılıklarını internetten kurar, güncel V7 Markdown dosyasını HTTPS üzerinden indirip doğrular, sunucuyu başlatır ve varsayılan tarayıcıda yerel arayüzü açar. V7 indirilemezse uygulama başlatılmaz; eski bir yerel V7 ile değerlendirme yapılmaz. İlk kurulumdan sonraki açılışlarda bağımlılık ve V7 güncelliği yeniden kontrol edilir.

Dağıtım ZIP’ine `.venv`, raporlar, önbellek, yüklenen dosyalar, Google oturum bilgileri, ders `mdler` klasörü veya başlangıç yerel V7 paketi dahil edilmez. `rules/rules.bin` öğretmen ZIP’inde bulunmaz; V7 yalnızca yapılandırılmış HTTPS kaynağından ilk çalıştırmada alınır. Ders Markdown’ı yalnızca iş süresince benzersiz geçici klasöre indirilir ve iş bitiminde silinir. İndirilen V7 içeriği de açık Markdown dosyası olarak yazılmaz; uygulamanın mevcut çalışma akışı için şifreli runtime paketine dönüştürülür. Yeni paket eski bir kurulum klasörünün üzerine çıkarılırsa, zorunlu uzak güncellemeden önce eski runtime `rules.bin` de kullanılmayacak şekilde kaldırılır.

## Word ve PDF rapor şablonu

Word raporu `templates/TYMM_Soru_Kontrol_Rapor_Sablonu.docx` içindeki kurumsal üstbilgi ve altbilgiyi kullanır. OGM logosu `assets/OGM_logo_beyaz_yatay.png` altında bulunur. Ders/sınıf, öğrenme çıktısı, süreç bileşeni, kapsanan sorular ve genel sonuç üst bilgi alanına; A, B, C ve D bölümleri ile bulgu/kanıt/revizyon alanları kurumsal renk hiyerarşisine yerleştirilir. PDF, mümkünse üretilen Word belgesinden dönüştürülür; Word veya LibreOffice bulunamazsa aynı içerik ve görsel kimlikle yerleşik PDF üreticisi kullanılır.

## V7 güncellemesi (paketin tamamını yeniden göndermeden)

V7 değiştiğinde öğretmenlere yeni ZIP göndermek zorunda kalmamak için güncelleme adresini bir kez `config.json` içinde tanımlayın:

```json
"rules_update": {
  "rules_url": "https://raw.githubusercontent.com/ersenaktas/tymm-v6-kurallari/main/soru_kontrol_V7.md",
  "manifest_url": "https://kurumunuz.example/tymm/manifest.json",
  "required": true,
  "timeout_seconds": 20
}
```

`rules_url` tanımlıysa öğretmen paketi her `Baslat.bat` çalıştırılışında public V7 Markdown dosyasını HTTPS üzerinden alır. İçerik UTF-8 ve boş değilse yerel çalışma için şifreli `rules.bin` paketine dönüştürülüp atomik olarak uygulanır. Öğretmen paketinde `required: true` kullanılır; GitHub erişilemezse veya dosya doğrulanamazsa uygulama açılmaz ve yerel eski V7’ye geçilmez. Bu basit modda GitHub’daki dosyayı değiştiren herkes yeni kuralları dağıtabilir; kullanıcı bu nedenle “super gizlilik” gerekmiyorsa uygundur. `manifest_url` de tanımlıysa `rules_url` önceliklidir.

## Tarayıcı kapanınca sunucunun otomatik kapanması

Arayüz açıkken tarayıcı her 20 saniyede yerel sunucuya kısa bir canlılık sinyali gönderir. Tarayıcı kapatılırsa veya bağlantı kesilirse, aktif değerlendirme yoksa varsayılan olarak 300 saniye sonra yerel sunucu ve onu başlatan işlem kapanır. Bu süre `config.json` içindeki `idle_shutdown_seconds` veya `PILOT_IDLE_TIMEOUT_SECONDS` ortam değişkeniyle 30–3600 saniye arasında ayarlanabilir. Değerlendirme sürerken sunucu kapanmaz; sonuçlandıktan sonra tarayıcı hâlâ kapalıysa sayaç işler.

Bu adres öğretmen bilgisayarlarından okunabilen, kimlik doğrulaması istemeyen bir HTTPS adresi olmalıdır. İlk dağıtım ZIP’ini bu ayarla oluşturduktan sonra her yeni V7 için yalnızca şu işlemleri yapın:

1. Güncel `soru_kontrol_V7.md` ve teslim istemi dosyanızı hazırlayın.
2. Proje klasöründe yayın paketi üretin:

   ```powershell
   .\publish_rules.ps1 `
     -RulesFile "D:\kaynaklar\soru_kontrol_V7.md" `
     -DeliveryFile "D:\kaynaklar\prompt.txt" `
     -Version "2026.08.21.1"
   ```

3. Oluşan `rules-release\manifest.json`, `rules.bin` ve `delivery.bin` dosyalarını aynı HTTPS klasörüne yükleyin. `manifest.json` içindeki göreli adresleri değiştirmeyin.

Öğretmen bir sonraki `Baslat.bat` çalıştırışında manifesti kontrol eder; SHA-256 özeti ve kural paketi doğrulanır, ardından dosyalar atomik olarak değiştirilir. Öğretmen paketinde `required: true` kullanıldığı için internet yoksa veya yayın paketi hatalıysa uygulama açılmaz ve yerel V7 kullanılmaz. Yalnızca geliştirme amaçlı yerel kurulumlarda `required: false` ile isteğe bağlı geri dönüş seçilebilir. Kural özeti değiştiği için eski rapor önbelleği yeni V7 ile yeniden kullanılmaz.

`publish_rules.ps1` yayın klasörüne düz metin V7 koymaz; yalnızca çalışma anında çözülen paketleri üretir. Bununla birlikte bu yöntem istemci tarafı obfuscation ve bütünlük doğrulamasıdır, mutlak gizlilik değildir. V7’nin öğretmen bilgisayarına hiç ulaşmaması gerekiyorsa kuralların merkezî bir sunucuda tutulduğu ayrı bir API mimarisi gerekir.

Kurulum sırasında “Python was not found” görürseniz Python 3.11 veya üzerini [python.org Windows indirmelerinden](https://www.python.org/downloads/windows/) kurun ve kurulum ekranında **Add Python to PATH** seçeneğini işaretleyin. PowerShell’i kapatıp yeniden açtıktan sonra komutları tekrarlayın.

Arayüzde klasör yolunu yazıp **Tara** ile birden çok PDF/DOCX seçebilir, dosyaları tarayıcıdan yükleyebilir veya soru metnini doğrudan yapıştırabilirsiniz. Yapıştırılan metin yalnız o iş için geçici Markdown kaynağı olur ve işlem sonunda silinir. İş başlatıldığında ilerleme ekranı otomatik açılır; mevcut adım, genel ilerleme ve dört ana aşama öğretmen odaklı bir görünümde izlenir. Durum bilgisi tam sayfa yenilenmeden arka planda güncellendiği için açılan işlem ayrıntıları, kaydırma konumu ve klavye odağı korunur. Çoklu işlemlerde canlı dosya kuyruğu görünür; tamamlanan her rapor seri bitmeden yeni sekmede görüntülenebilir veya Word/PDF olarak indirilebilir. Seri tamamlandığında Word ve PDF ZIP paketleri de sunulur. Rapor adı, seçilen dosya ya da verilen metin adından `…-rapor` olarak üretilir.

İlk kullanımda arayüzde **Gmail ile giriş yap** düğmesine basın. Geçerli bir yerel Gmail oturumu varsa uygulama bunu doğrular; yoksa giriş penceresi açılır. Parola veya çerez uygulama alanına alınmaz. Dağıtım kurulumu yalnızca `notebooklm-py[browser]` ekini kullanır; Python 3.13+ Windows'ta derleme sorunu çıkaran `rookiepy`/`[cookies]` eki özellikle kurulmaz. Python 3.13'te kaldırılan standart `cgi` modülü için yalnızca bu sürümde `legacy-cgi` uyumluluk paketi kurulur. Firefox çerez aktarımı gerekiyorsa Python 3.12 veya altındaki ayrı bir ortamda `notebooklm-py[cookies]` kurulmalıdır.

NotebookLM oturumu daha sonra geçersizleşirse iş durumu sayfasında **Gmail girişini yenile** düğmesi görünür. Bu düğme eski yerel profili temizleyip Chrome’da yeni giriş akışını başlatır; normal **Gmail ile giriş yap** düğmesi geçerli oturumu korur.

PDF/DOCX dosyalarını tekli, toplu, taranmış yerel klasörden veya tarayıcı yüklemesiyle seçebilirsiniz. Ders önce dosya adı ve belgenin ilk bölümlerindeki ders kodu/başlıktan algılanır; güvenli eşleşme olmazsa arayüzden elle seçilir. Her iş kendi geçici defterini ve kaynaklarını kullanır; `finally` temizliği başarılı/hatalı tüm yollarda çalışır. Raporlar `outputs/` altında Markdown, JSON, DOCX ve PDF olarak üretilir. Her geçici deftere yalnız üç kaynak eklenir: GitHub'dan alınan güncel V7 yönergesi, ilgili dersin GitHub'dan alınan özgün adlı `.md` kaynağı ve soru kaynağı. Ardından şifreli `delivery.bin` paketinden bellekte çözülen V7 A/B/C/D sorun raporu istemi gönderilir. Paket içeriği kaynakta kısaltılmaz veya özetlenmez; eksik paket halinde azaltılmış değerlendirmeye geçilmez ve iş başlatılmaz.

İlk yanıt, geçici defterde NotebookLM’nin ayrıntılı yanıt modu açıkken tam V7 değerlendirmesi olarak alınır. Yaygın başlık ve liste farklılıkları yalnız biçimsel olarak normalleştirilir. V7 yapısı eksikse aynı geçici defterde bağımsız bütünlük denetimi yapılır ve en kapsamlı tek NotebookLM yanıtı korunur; Python farklı yanıt parçalarını birleştirmez veya değerlendirme kararı üretmez. Yapı yine tamamlanamazsa yanıltıcı Word/PDF oluşturulmaz, alınan Markdown yanıtı korunur. Hiçbir ek kaynak yüklenmez, yönerge/oturum içeriği loglara yazılmaz ve defter iş sonunda silinir.

Her işte yeni ve geçici bir NotebookLM defteri oluşturulur. Böylece sabit notebook sohbet geçmişi bir sonraki değerlendirmeye taşınmaz. Aynı soru dosyası, aynı ders kaynağı ve aynı V7/prompt paketi tekrar seçilirse `outputs/.cache/` içindeki doğrulanmış rapor kullanılır; bu, aynı girdinin her seferinde farklı bir cevap üretmesini engeller. Arayüzdeki **önbelleği kullanma; yeniden değerlendir** seçeneği yalnızca açıkça ikinci bir NotebookLM görüşü istenirse işaretlenmelidir.

## Güvenlik sınırları

- Bu pilot yerel oturumu ve dosyaları kullanıcı profili altında saklar; Google şifresini toplamaz.
- Yerel loglara kontrol yönergesi, ham model yanıtı veya oturum çerezi yazılmaz.
- `rules/rules.bin`, öğretmen ZIP'inde bulunmaz; her açılışta GitHub'dan alınan V7 içeriğinden çalışma anında oluşturulur. `rules/delivery.bin`, teslim istemini dağıtım klasöründe açık metin bırakmamak için çalışma anında çözülen pakettir.
- Bu tasarım **dosyayı doğrudan dağıtmama / obfuscation** düzeyindedir; teknik kullanıcıya karşı mutlak gizlilik sağlamaz. Anahtar aynı istemcide bulunduğu için gerçek gizlilik değildir.
- Gelecekte merkezî sunucuya geçiş için `RuleProvider` ve `NotebookProvider` arayüzleri ayrıdır; merkezî çözümleme/anahtar yönetimi bu arayüzlere taşınabilir.

Gerçek `notebooklm-py` sağlayıcısını kullanmak için `pip install -e ".[notebooklm,web]"` gerekir. İlk bağlantıda arayüz Gmail giriş penceresini açar; parola uygulamaya girmez. Sağlayıcı adaptörü, paket API'si değişebildiğinden tek dosyada tutulmuştur. `FakeNotebookProvider` ile bağlantı ve iş akışı test edilebilir.

Gerçek kullanım sırası: arayüzde **Gmail ile giriş yap** düğmesine basın, gerekirse tarayıcıdaki Gmail girişini tamamlayın, sonra PDF/DOCX dosyalarını ve gerekiyorsa ders kaynağını seçip **Değerlendirmeyi başlat** düğmesine basın. Her dosya için yeni geçici defter açılır; yönerge, ders kaynağı ve soru eklenir; cevap alındıktan sonra defter `finally` içinde silinir. **Bağlantıyı kaldır** düğmesi `notebooklm auth logout` ile yerel oturum dosyalarını temizler.

## Geliştirici doğrulaması

```powershell
python -m pytest -q
python -m pilot.cli --fake --file examples/sample.txt
```

Arayüz gerçek sağlayıcıyla açılır. Sahte sağlayıcı yalnızca test için `PILOT_FAKE=1` ortam değişkeni açıkça verilirse kullanılır.

Dağıtım klasörüne `soru_kontrol_V7.md`, ders `.md` dosyaları, `prompt.txt`, `.state`, `storage_state.json`, tarayıcı profili veya Google oturum bilgisi konulmaz. V7 GitHub'dan belleğe alınarak çalışma paketine dönüştürülür; teslim istemi yalnızca çalışma anında çözülen paket olarak bulunur.
