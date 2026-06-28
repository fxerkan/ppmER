# Veri Modeli Dokümantasyonu

## Neden Anlık Görüntü Tabanlı Tarihsel Veri Modeli?

Çoğu Jira analitik entegrasyonu verilerinizin *mevcut* durumunu çeker. Bu şu anlama gelir:

- Geçen ay bir konunun durumunun ne olduğunu göremezsiniz
- Konuların her durumda ne kadar zaman geçirdiğini ölçemezsiniz
- Birisi Jira'dan bir iş günlüğünü silerse, geçmişiniz kaybolur
- Çaba takvim dönemlerine bağlanmadığı için kapasite raporları hatalı olur

Bu yığın, tüm bu sorunları çözen **anlık görüntü tabanlı tarihsel modeli** kullanır:

- Her pipeline çalıştığında, mevcut durumu zaman damgalı anlık görüntü olarak kaydeder
- Jira'da silinse bile iş günlükleri kalıcı olarak saklanır
- Doğru kapasite planlaması için çaba takvim gün/hafta/aylara dağıtılır
- Anlık görüntü deltalarından durum değişikliği hızı hesaplanabilir

---

## 3 Katmanlı Mimari

```
Katman 1: STAGING
  - Kaynak: raw_jira şeması (dlt tarafından yüklenir)
  - Amaç: tür dönüştürme, sütun yeniden adlandırma, temel tekilleştirme
  - İsimlendirme: stg_jira__<varlık>

Katman 2: CORE
  - Kaynak: staging görünümleri
  - Amaç: iş mantığı, boyut/olgu modelleme, anlık görüntü yönetimi
  - İsimlendirme: dim_<varlık>, fact_<varlık>

Katman 3: MARTS
  - Kaynak: core tablolar
  - Amaç: iş amaçlı toplamalar, KPI'lar, istisna raporları
  - İsimlendirme: mart_<ad>, agg_<ad>, rpt_<ad>
```

---

## Varlık İlişki Genel Bakışı

```
dim_projects ----+
                 |
dim_users -------+----> fact_worklogs
                 |
dim_issues ------+----> fact_issues
                 |
                 +----> fact_distributed_efforts
```

---

## Tablo Açıklamaları

### Staging Katmanı

| Model | Kaynak Tablo | Açıklama |
|-------|------------|----------|
| `stg_jira__issues` | `raw_jira.issues` | Tiplendirilmiş sütunlarla tüm Jira konuları |
| `stg_jira__worklogs` | `raw_jira.worklogs` | Tüm iş günlüğü girişleri |
| `stg_jira__users` | `raw_jira.users` | Jira kullanıcı hesapları |
| `stg_jira__projects` | `raw_jira.projects` | Jira projeleri |
| `stg_jira__issue_links` | `raw_jira.issue_links` | Konu ilişkileri (engeller, ilgili, vb.) |
| `stg_jira__issue_subtasks` | `raw_jira.issue_subtasks` | Üst-alt konu ilişkileri |
| `stg_jira__issue_custom_fields` | `raw_jira.issue_custom_fields` | Konu başına özel alan değerleri |
| `stg_jira__project_properties` | `raw_jira.project_properties` | Proje düzeyinde yapılandırma verileri |

### Core Katmanı

| Model | Tür | Açıklama |
|-------|-----|----------|
| `dim_projects` | Boyut | Proje özellikleri (anahtar, ad, tür, lider) |
| `dim_projects_snapshot` | Anlık Görüntü | Zaman içinde tarihsel proje durumu |
| `dim_issues` | Boyut | Mevcut konu durumu |
| `dim_issues_snapshot` | Anlık Görüntü | Her pipeline çalıştırmada konu durumu — trend analizi için bunu kullanın |
| `dim_users` | Boyut | Kullanıcı profilleri ve ekip atamaları |
| `fact_worklogs` | Olgu | Yazar, konu, süre, zaman damgasıyla her iş günlüğü girişi |
| `fact_issues` | Olgu | Toplu konu metrikleri (hikaye puanları, zaman tahminleri vs gerçekler) |
| `fact_distributed_efforts` | Olgu | Kapasite raporlaması için takvim günlerine dağıtılan iş günlüğü çabası |

### Temel Tasarım Kararları

#### `dim_issues_snapshot`
Pipeline her çalıştığında, `snapshot_date = BUGÜN` ile yeni bir satır yazılır. Bu sayede:
```sql
-- Geçen çeyreğin sonunda tüm konuların durumu
SELECT issue_key, status_name, assignee_display_name
FROM core.dim_issues_snapshot
WHERE snapshot_date = '2024-12-31'
```

#### `fact_distributed_efforts`
"Pazartesi kaydedilen 8 saatlik" iş günlüğü tek bir satır olarak saklanır. Ancak aylık kapasite raporları için, bu 8 saat Ocak toplamında görünmelidir. `fact_distributed_efforts`, ilgili takvim dönemine (gün/hafta/ay/çeyrek) göre çabayı dağıtarak bunu yönetir:
```sql
SELECT
    calendar_month,
    project_key,
    SUM(distributed_hours) as aylik_caba
FROM core.fact_distributed_efforts
GROUP BY calendar_month, project_key
```

#### `fact_worklogs`
Değişmez tarihsel kayıt. Jira'dan bir iş günlüğü silinse bile burada kalır. Kaynak kayıt kaybolduğunda `is_deleted` bayrağı `true` olarak ayarlanır.

### Marts Katmanı

| Model | Açıklama |
|-------|----------|
| `mart_portfolio_dashboard` | Tüm KPI'larla proje başına bir satır (konular, saatler, sağlık puanı) |
| `agg_project_health` | Proje sağlık göstergeleri: gecikmiş sayı, eksik çaba, hız trendi |
| `rpt_missing_effort` | İş günlükleri olması gereken ama olmayan konular (yapılandırılabilir eşikler) |
| `fact_financial_dashboard_2025` | Finansal kapasite görünümü: döneme göre planlanan vs gerçek çaba |
| `fact_financial_dashboard_2026` | Mevcut yıl için aynı model |

---

## SQL Örnekleri

### Bu ay proje başına kaç saat loglandı?
```sql
SELECT
    p.project_name,
    SUM(w.time_spent_hours) as saatler
FROM core.fact_worklogs w
JOIN core.dim_projects p ON w.project_key = p.project_key
WHERE DATE_TRUNC('month', w.started_at) = DATE_TRUNC('month', NOW())
GROUP BY p.project_name
ORDER BY saatler DESC;
```

### Son 7 günde hangi konular durum değiştirdi?
```sql
SELECT
    s1.issue_key,
    s1.status_name as eski_durum,
    s2.status_name as yeni_durum,
    s2.snapshot_date as degisim_tarihi
FROM core.dim_issues_snapshot s1
JOIN core.dim_issues_snapshot s2
    ON s1.issue_key = s2.issue_key
    AND s2.snapshot_date = s1.snapshot_date + INTERVAL '1 day'
    AND s1.status_name != s2.status_name
WHERE s2.snapshot_date >= NOW() - INTERVAL '7 days';
```
