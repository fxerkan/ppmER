# Yapay Zeka Ajanı Entegrasyon Rehberi

Bu rehber, doğal dil veri analizi için çeşitli yapay zeka ajanlarının PPM Veri Yığınına bağlanmasını kapsar.

---

## Dahili Sohbet Ajanı (Gradio)

Yığın, **http://localhost:7860** adresinde kullanıma hazır bir sohbet arayüzü içerir.

Herhangi bir OpenAI uyumlu API ile çalışır. `.env` dosyasında ayarlayın:

```env
OPENAI_API_KEY=anahtariniz
OPENAI_BASE_URL=https://api.openai.com/v1   # veya herhangi bir uyumlu uç nokta
OPENAI_MODEL=gpt-4o-mini
```

---

## Claude Code Kurulumu (MCP Sunucusu)

Dahil edilen `agent/mcp_server.py`, Claude Code veya Cursor ile doğrudan entegrasyon için Model Context Protocol'ü (MCP) uygular.

### Yapılandırma

Claude Code MCP yapılandırmanıza ekleyin (`~/.claude/mcp.json` veya proje `.claude/mcp.json`):

```json
{
  "mcpServers": {
    "ppm-data-stack": {
      "command": "python",
      "args": ["/mutlak/yol/jira-ppm-data-stack/agent/mcp_server.py"],
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

### Mevcut MCP Araçları

| Araç | Açıklama |
|------|----------|
| `query_db` | Veri ambarına karşı SELECT SQL sorgusu çalıştır |
| `list_schemas` | Tüm şema ve tabloları listele |
| `list_dbt_models` | Tüm dbt dönüşüm modellerini listele |

### Claude Code'da Örnek Kullanım

MCP yapılandırıldıktan sonra Claude Code bu araçları doğrudan kullanabilir:
```
> En fazla açık konuya sahip projeler hangileri?
Claude uygun SQL ile query_db'yi çağıracak ve sonuçları döndürecektir.
```

---

## Anthropic Claude API Kullanımı (OpenAI Uyumlu)

Sohbet ajanını Anthropic'in OpenAI uyumlu uç noktasına yönlendirin:

```env
OPENAI_API_KEY=sk-ant-anthropic-api-anahtariniz
OPENAI_BASE_URL=https://api.anthropic.com/v1
OPENAI_MODEL=claude-3-5-haiku-20241022
```

Not: Anthropic'in OpenAI uyumlu uç noktası, sohbet ajanının kullandığı araç çağrısını destekler.

---

## OpenAI (GPT) Kullanımı

Varsayılan yapılandırma. Ayarlayın:
```env
OPENAI_API_KEY=sk-openai-anahtariniz
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini          # en ucuz seçenek, iyi çalışır
# veya: gpt-4o daha iyi akıl yürütme için
```

---

## Google Gemini Kullanımı

Gemini'nin OpenAI uyumlu bir uç noktası vardır:

```env
OPENAI_API_KEY=gemini-api-anahtariniz
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_MODEL=gemini-2.0-flash
```

API anahtarı almak için: https://aistudio.google.com/apikey

---

## Yerel Ollama Kullanımı (API Anahtarı Gerekmez)

Sıfır maliyetle modelleri yerel olarak çalıştırın. https://ollama.ai adresinden Ollama'yı kurun, ardından:

```bash
ollama pull qwen2.5-coder:7b   # SQL görevleri için iyi
```

```env
OPENAI_API_KEY=ollama           # yer tutucu, kullanılmaz
OPENAI_BASE_URL=http://host.docker.internal:11434/v1
OPENAI_MODEL=qwen2.5-coder:7b
```

Not: Yerel modeller, karmaşık SQL oluşturma için daha yavaş ve daha az doğru olabilir.

---

## Kullanım Senaryosuna Göre Örnek İstekler

### Portföy Sağlık Kontrolü
```
"Her aktif proje için tek satırlık durum ver: toplam konular, açık konular, bu ay kaydedilen saatler ve iş yükünün dengeli görünüp görünmediği."
```

### Eksik Çaba Denetimi
```
"Durumu In Progress veya In Review olan, Story Points değeri > 0 olan ama son 14 günde sıfır iş günlüğü olan tüm konuları bul. Atanan kişiye göre grupla."
```

### Sprint Hızı
```
"Son 8 hafta boyunca haftalık tamamlanan hikaye puanlarının ortalamasını proje bazında hesapla."
```

### Kullanıcı İş Yükü Analizi
```
"Bu ay aşırı yüklenenler (160 saatten fazla loglanmış) kimler? Yetersiz yüklenenler (80 saatten az) kimler?"
```

### Konu Yaşı Raporu
```
"Tüm projelerdeki en eski 20 açık konuyu, atanan kişisi, önceliği ve kaç gündür açık olduğuyla göster."
```

### Özel Alan Analizi
```
"story_points özel alanı null olan ama konu türü Story veya Task olan ve durumu Done olmayan tüm konuları listele."
```

---

## MCP ile Doğrudan SQL

MCP sunucusunu hassas SQL sorguları için de kullanabilirsiniz:

```sql
-- Örnek: 30 gündür aktivitesi olmayan projeleri bul
SELECT p.project_name, MAX(w.started_at) as son_aktivite
FROM core.dim_projects p
LEFT JOIN core.fact_worklogs w ON p.project_key = w.project_key
GROUP BY p.project_name
HAVING MAX(w.started_at) < NOW() - INTERVAL '30 days'
   OR MAX(w.started_at) IS NULL
ORDER BY son_aktivite NULLS FIRST;
```

---

## Güvenlik Notları

- MCP sunucusu ve sohbet ajanı yalnızca `SELECT` sorgularına izin verir — yazma, silme veya DDL yok
- Üretim kullanımı için Postgres kullanıcısının yalnızca `SELECT` ayrıcalıklarına sahip olması gerekir
- API anahtarları `.env` dosyasında saklanır ve gitignore'dadır — asla commit etmeyin
- Ekip kullanımı için yığını bir VPN arkasında veya Metabase kullanıcı kimlik doğrulamasıyla çalıştırmayı düşünün
