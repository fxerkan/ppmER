# Kurulum Rehberi

Bu rehber, Docker veya komut satırı araçlarına aşina olmayan PMO/iş kullanıcıları için yazılmıştır. Her adımı sırayla takip edin.

---

## Adım 1: Ön Koşullar

İki şeye ihtiyacınız var:

### Docker Desktop
1. https://www.docker.com/products/docker-desktop/ adresine gidin
2. İşletim sisteminiz için indirin (Mac veya Windows)
3. Docker Desktop'ı kurun ve başlatın
4. Docker Desktop ayarlarında Docker'a en az **4GB RAM** ayırın
   - Mac: Docker Desktop > Settings > Resources > Memory > 4GB+
   - Windows: Docker Desktop > Settings > Resources > Memory > 4GB+

### Git (projeyi klonlamak için)
- Mac: Terminal'i açın, `git --version` yazın. Kurulu değilse macOS kurmanızı isteyecektir.
- Windows: https://git-scm.com/download/win adresinden indirin

---

## Adım 2: Jira API Token Alma

1. https://sirketiniz.atlassian.net adresinde Jira'ya giriş yapın
2. Profil resminize tıklayın (sağ üst) > **Hesabı yönet**
3. **Güvenlik** sekmesine gidin
4. **API tokenları oluştur ve yönet**'e tıklayın
5. **API token oluştur**'a tıklayın
6. "PPM Veri Yığını" gibi bir ad verin
7. **Oluştur**'a tıklayın ve **tokeni kopyalayın** — bir daha göremezsiniz

---

## Adım 3: İndirme ve Yapılandırma

Terminal'i (Mac) veya Komut İstemi'ni (Windows) açın:

```bash
# Projeyi klonlayın
git clone https://github.com/fxerkan/jira-ppm-data-stack.git
cd jira-ppm-data-stack

# Örnek yapılandırmayı kopyalayın
cp .env.example .env
```

Şimdi `.env` dosyasını herhangi bir metin düzenleyicide (Not Defteri, TextEdit, VS Code) açın ve doldurun:

```
JIRA_SUBDOMAIN=sirketiniz          # .atlassian.net öncesindeki kısım
JIRA_EMAIL=siz@sirketiniz.com      # Jira giriş e-postanız
JIRA_API_TOKEN=<tokeni-buraya-yapıştırın>  # Adım 2'deki token
POSTGRES_PASSWORD=guclu-bir-sifre-secin
CB_ADMIN_PASSWORD=yonetici-sifresi-secin
```

Dosyayı kaydedin.

---

## Adım 4: Yığını Başlatma

Terminalinizde (proje klasöründe olduğunuzdan emin olun):

```bash
docker-compose up -d
```

Bu, gerekli tüm Docker görüntülerini (~2-3 GB) indirecek ve servisleri başlatacaktır. İlk çalıştırmada 5-10 dakika sürer. İlerlemeyi şu komutla kontrol edebilirsiniz:

```bash
docker-compose ps
```

Birkaç dakika sonra tüm servisler `Up` veya `healthy` göstermelidir.

---

## Adım 5: İlk Veri Yüklemesini Çalıştırma

Tarayıcınızı açın ve şu adrese gidin: **http://localhost:6789**

Bu, pipeline orkestratörü olan Mage AI'dır.

1. Sol kenar çubuğunda **Pipelines**'a tıklayın
2. `master_initial_jira`'yı bulun — bu TÜM Jira geçmişinizi yükler
3. Pipeline'a tıklayın, ardından **Run pipeline now**'a tıklayın
4. Günlükleri izleyin — ne kadar Jira veriniz olduğuna bağlı olarak 10-60 dakika sürebilir

Günlük güncellemeler için (ilk yüklemeden sonra) `master_daily_jira`'yı kullanın.

---

## Adım 6: Metabase'i Açma ve İlk Gösterge Panelinizi Oluşturma

1. http://localhost:3000 adresine gidin
2. **Başlayalım**'a tıklayın
3. Bir yönetici hesabı oluşturun (bu yalnızca yereldir)
4. "Verilerinizi ekleyin" adımında **PostgreSQL**'i seçin:
   - Host: `postgres`
   - Port: `5432`
   - Veritabanı adı: `ppm_datawarehouse`
   - Kullanıcı adı: `ppm_user`
   - Parola: (`.env` dosyasında `POSTGRES_PASSWORD` olarak ayarladığınız)
5. **Veritabanına bağlan**'a tıklayın

### İlk sorunuzu (raporunuzu) oluşturma:

1. **+ Yeni > Soru**'ya tıklayın
2. `ppm_datawarehouse` veritabanınızı seçin
3. **Native query** (SQL) seçin
4. Bu sorguyu yapıştırın:

```sql
SELECT
    project_key,
    COUNT(*) as toplam_konular,
    COUNT(CASE WHEN status_category != 'Done' THEN 1 END) as acik_konular
FROM core.fact_issues
GROUP BY project_key
ORDER BY acik_konular DESC;
```

5. Sonuçları görmek için **Çalıştır**'a tıklayın
6. Soru olarak kaydetmek için **Kaydet**'e tıklayın
7. Yeni bir gösterge paneline ekleyin

5 kullanıma hazır gösterge paneli sorgusu için [metabase/README.md](../../metabase/README.md) dosyasına bakın.

---

## Adım 7: Yapay Zeka Sohbet Ajanını Kullanma

1. http://localhost:7860 adresine gidin
2. Sohbet kutusuna bir soru yazın, örneğin:
   - "Her projenin kaç açık konusu var?"
   - "Bu hafta hiç saat loglamayan kullanıcıları göster"
   - "Son tarihini kaçıracak risk altındaki epicler hangileri?"

Yapay zeka ajanı otomatik olarak veritabanınızı sorgulayacak ve sonuçları tablolarla birlikte sade dilde döndürecektir.

---

## Günlük Kullanım

İlk kurulumdan sonra tipik iş akışınız şöyle olacak:

1. **Pipeline'lar otomatik çalışır** — Mage AI her gece `master_daily_jira`'yı çalıştıracak şekilde yapılandırılmıştır
2. **Metabase'deki gösterge panellerini kontrol edin** — her sabah http://localhost:3000 adresini açın
3. **Yapay zeka ajanında soru sorun** — anlık analiz için http://localhost:7860

Yığını durdurmak için: `docker-compose down`
Yeniden başlatmak için: `docker-compose up -d`

---

## Sorun Giderme

**"docker-compose: command not found" hatası**
`docker compose up -d` deneyin (tire olmadan — yeni Docker sürümleri bu sözdizimini kullanır).

**Servisler "Exiting" durumu gösteriyor**
Günlükleri kontrol edin: `docker-compose logs <servis-adı>` (örn. `docker-compose logs mage`)

**Jira pipeline "401 Unauthorized" hatasıyla başarısız oluyor**
`.env` dosyasındaki API tokenınız veya e-postanız hatalı. Tekrar kontrol edin ve `docker-compose restart mage` çalıştırın.

**Metabase veritabanına bağlanamıyorum**
Pipeline'ın en az bir kez çalıştığından emin olun. dbt dönüşümleri çalışmadan `core` şeması var olmayacaktır.

**Disk alanı tükeniyor**
Docker görüntüleri ve veriler ~5-10GB yer kaplar. Kullanılmayan görüntüleri temizlemek için `docker system prune` çalıştırın.
