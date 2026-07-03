{% docs __overview__ %}

# PPM Data Stack — veri kataloğuna hoş geldiniz

Bu katalog, **ppmER** (Project & Portfolio Management Enhanced Reporting) veri yığınının tüm modellerini belgeler.
Jira'dan ham veri alımından iş zekası raporlarına kadar 3 katmanlı dbt dönüşüm mimarisini yönetir.

## Veri akışı

```
Jira Cloud → DLT (raw_jira) → staging (temizleme) → core (dim/fact) → mart (raporlama)
```

## Katmanlar

| Katman | Şema | Amaç |
|--------|------|-------|
| Staging | `staging` | Ham veri temizleme, tip dönüşümü, tekrar giderme |
| Core | `core` | `dim_*` boyut ve `fact_*` olgu tabloları |
| Mart | `mart` | İş düzeyi agregasyonlar ve raporlar |

## Önemli modeller

| Model | Açıklama |
|-------|----------|
| `staging.stg_jira__issues` | Tüm Jira issue'ları (temizlenmiş) |
| `staging.stg_jira__worklogs` | Zaman kayıtları |
| `core.dim_projects` | Proje boyutu |
| `core.dim_users` | Kullanıcı boyutu |
| `core.fact_worklogs` | Worklog olgu tablosu (tarihsel snapshot) |
| `core.fact_issues` | Issue olgu tablosu |
| `mart.mart_portfolio_dashboard` | Portföy genel bakış |
| `mart.agg_project_health` | Proje sağlık metrikleri |
| `mart.rpt_missing_effort` | Eksik zaman kaydı raporu |

## Bağlantılar

- **Metabase** (Raporlar): [http://localhost:3000](http://localhost:3000)
- **Mage AI** (Orkestrasyon): [http://localhost:6789](http://localhost:6789)
- **Portal**: [http://localhost:8080](http://localhost:8080)

{% enddocs %}
