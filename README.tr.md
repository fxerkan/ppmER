# Jira PPM Veri Yığını

Jira üzerine kurulu, açık kaynaklı bir Proje & Portföy Yönetimi (PPM) veri platformu. Jira verilerinizi Docker ile yerel olarak çalışan, otomatik pipeline'lar, tarihsel anlık görüntüler, BI gösterge panelleri ve yapay zeka sohbet ajanıyla üretim kalitesinde bir analitik veri ambarına dönüştürün.

**Neden bu var**: Kurumsal PPM araçları (Planview, Clarity vb.) yılda onbinlerce dolara mal olur. Bu yığın, açık kaynak araçlar, mevcut Jira verileriniz ve tek bir `docker-compose up` komutuyla aynı analitik yetenekleri sağlar.

## Mimari

```
+-------------------------------------------------------------+
|                  Jira PPM Veri Yığını                       |
+-------------+---------------+---------------+---------------+
|   Kaynaklar |   Yükleme     | Dönüşüm       |   Sunum       |
+-------------+---------------+---------------+---------------+
|             |               |               |               |
|  Jira API   |     dlt       |    dbt        |   Metabase    |
|  SharePoint |   (Python)    |  (SQL modeller| Gösterge Paneli|
|             |               |               |               |
|             |      v        |      v        |   CloudBeav.  |
|             |  Mage AI      |  PostgreSQL   |   (SQL UI)    |
|             | (orkestrasyon)|  Veri Ambarı  |               |
|             |               |               |  Yapay Zeka   |
|             |               |               |  Sohbet Ajanı |
+-------------+---------------+---------------+---------------+
```

## Veri Akışı

```
Jira API
  |
  v (dlt pipeline'ları)
raw_jira şeması       <- ham JSON benzeri tablolar (konular, iş günlükleri, kullanıcılar, projeler)
  |
  v (dbt staging)
staging şeması        <- tiplendirilmiş, temizlenmiş, yeniden adlandırılmış sütunlar
  |
  v (dbt core)
core şeması           <- dim_* (boyutlar) + fact_* (anlık görüntülü olgular)
  |
  v (dbt marts)
mart şeması           <- iş KPI'ları, portföy görünümleri, istisna raporları
  |
  v
Metabase / CloudBeaver / Yapay Zeka Ajanı
```

## Servisler

| Servis | URL | Amaç |
|--------|-----|-------|
| Mage AI | http://localhost:6789 | Pipeline orkestrasyon |
| Metabase | http://localhost:3000 | BI gösterge panelleri |
| CloudBeaver | http://localhost:8978 | SQL tarayıcı |
| dbt Dokümantasyon | http://localhost:8081 | Veri kökenlilik dokümantasyonu |
| Yapay Zeka Ajanı | http://localhost:7860 | Doğal dil sorguları |
| PostgreSQL | localhost:15432 | Veri ambarı |

## Hızlı Başlangıç

### 1. Ön Koşullar

- Docker Desktop (en az 4GB RAM ayrılmış)
- API erişimine sahip Jira Cloud hesabı

### 2. Klonlama ve Yapılandırma

```bash
git clone https://github.com/fxerkan/jira-ppm-data-stack.git
cd jira-ppm-data-stack
cp .env.example .env
```

`.env` dosyasını Jira bilgilerinizle düzenleyin:
```env
JIRA_SUBDOMAIN=sirketiniz          # sirketiniz.atlassian.net
JIRA_EMAIL=siz@example.com
JIRA_API_TOKEN=api-tokeniniz       # https://id.atlassian.com/manage-profile/security/api-tokens adresinden alın
POSTGRES_PASSWORD=guclu_sifre_giriniz
```

### 3. Yığını Başlatma

```bash
docker-compose up -d
```

Tüm servislerin başlaması için yaklaşık 2 dakika bekleyin. Durumu kontrol edin:
```bash
docker-compose ps
```

### 4. İlk Veri Yüklemesini Çalıştırma

Mage AI'ı http://localhost:6789 adresinde açın ve tam geçmiş yükleme için `master_initial_jira` pipeline'ını, artımlı güncellemeler için `master_daily_jira`'yı çalıştırın.

Ya da terminalden çalıştırın:
```bash
docker exec ppm-mage mage run default_repo master_initial_jira
```

### 5. Metabase'i Açma

http://localhost:3000 adresine gidin, kurulumu tamamlayın, PostgreSQL bağlantınızı ekleyin (host: `postgres`, port: `5432`, db: `ppm_datawarehouse`, user: `ppm_user`) ve gösterge panelleri oluşturmaya başlayın.

5 kullanıma hazır gösterge paneli SQL sorgusu için [metabase/README.md](metabase/README.md) dosyasına bakın.

## Neden Tarihsel Veri Modeli?

Çoğu Jira analitik aracı yalnızca mevcut durumu gösterir. Bir konu geçen hafta "Devam Ediyor"dan "Tamamlandı"ya değiştiyse, bunun ne zaman gerçekleştiğini göremez veya hız ölçemezsiniz.

Bu yığın, **anlık görüntü tabanlı tarihsel veri modeli** kullanır:

- `dim_issues_snapshot` — konu durum değişikliklerini zaman içinde yakalar (durum, atanan kişi, hikaye puanları)
- `dim_projects_snapshot` — proje meta veri geçmişi
- `fact_worklogs` — her iş günlüğü girişi, Jira silmelerinden sonra bile geçmişi koruyarak
- `fact_distributed_efforts` — kaydedilen çabayı kapasite raporlaması için takvim dönemlerine dağıtır

Bu sayede şu soruları yanıtlayabilirsiniz: "X projesi üç ay önce hangi durumdaydı?", "Bu konuyu kim değiştirdi ve ne zaman?", "Sprint başına ne kadar çaba kaydedildi, tahmine karşı?"

## Yapay Zeka Ajanı

Yığın, verilerinize bağlanan bir yapay zeka sohbet arayüzü içerir:

```bash
open http://localhost:7860
```

Şunları sorun:
- "Her projenin kaç açık konusu var?"
- "Bu ay en çok saat kayıt eden 5 kullanıcıyı göster"
- "30 günden uzun süredir açık olan ve hiç iş günlüğü olmayan konular hangileri?"

### Claude Code / Cursor MCP ile Bağlantı

```json
{
  "mcpServers": {
    "ppm-data-stack": {
      "command": "python",
      "args": ["./agent/mcp_server.py"],
      "env": {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "15432",
        "POSTGRES_DB": "ppm_datawarehouse",
        "POSTGRES_USER": "ppm_user",
        "POSTGRES_PASSWORD": "sifreniz"
      }
    }
  }
}
```

## Teknoloji Yığını

| Bileşen | Araç | Sürüm |
|---------|------|-------|
| Veri Yükleme | [dlt](https://dlthub.com) | 0.5.x |
| Orkestrasyon | [Mage AI](https://mage.ai) | guncel |
| Dönüşüm | [dbt](https://getdbt.com) | 1.8+ |
| Veri Ambarı | PostgreSQL | 15 |
| BI | [Metabase](https://metabase.com) | guncel |
| SQL Tarayıcı | [CloudBeaver](https://cloudbeaver.io) | 24.2 |
| Yapay Zeka Ajanı | Gradio + OpenAI SDK | 4.x |

## Katkıda Bulunma

PR'lar memnuniyetle karşılanır. Lütfen:
1. Değişiklikleri odaklı tutun (gereksiz eklenti yapmayın)
2. Göndermeden önce `docker-compose up` ile test edin
3. Veri modelini değiştirirken ilgili dokümantasyonu güncelleyin
4. `.env` veya sırları commit etmeyin

## Lisans

MIT
