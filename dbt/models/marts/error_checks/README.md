# Error Checks - Data Quality Validation Scripts

Bu dizin, PPM Data Warehouse'daki veri kalitesi kontrollerini içerir. Her SQL scripti, belirli bir veri kalitesi kontrolü yapar ve hata/tutarsızlık bulunduğunda sonuç döner. Hata yoksa boş döner.

## Dizin Yapısı

### 1. master_data/
Master data (dimension) tablolarındaki veri kalitesi kontrolleri:
- Eksik/null değerler
- Referans bütünlüğü
- Duplicate kayıtlar
- Veri tipi uyumsuzlukları

### 2. transactional_data/
Transaction (fact) tablolarındaki veri kalitesi kontrolleri:
- Fact tabloları arasında tutarlılık
- Hesaplama doğruluğu
- Negatif değerler (olmaması gereken yerlerde)
- Mantık hataları

### 3. row_count_checks/
Satır sayısı kontrolleri (raw -> staging -> core -> mart):
- Raw layer satır sayısı vs staging
- Staging satır sayısı vs core
- Core satır sayısı vs mart
- Aggregate sonuçlarının doğruluğu

### 4. data_quality/
Genel veri kalitesi kontrolleri:
- Güncellik (freshness) kontrolleri
- Doluluk oranı kontrolleri
- Pattern uyumsuzlukları
- Anomali tespitleri

### 5. sharepoint_data/
SharePoint'ten gelen manuel veri kontrolleri:
- Eksik proje bilgileri
- Hatalı financial_code değerleri
- Adjustment tutarsızlıkları
- Capex/Opex oranları

### 6. jira_data/
Jira'dan gelen veri kontrolleri:
- Eksik issue bilgileri
- Worklog anomalileri
- Epic bağlantıları
- Project assignment hataları

## Kullanım

Her SQL scripti bağımsız çalıştırılabilir:

```sql
-- Örnek: Project master data kontrolü
\i error_checks/master_data/01_dim_projects_missing_data.sql
```

Hata varsa sonuç döner, yoksa boş döner.

## Script Adlandırma

Format: `[sıra_no]_[tablo/konu]_[kontrol_tipi].sql`

Örnekler:
- `01_dim_projects_missing_data.sql`
- `02_fact_worklogs_negative_values.sql`
- `03_row_count_raw_vs_staging.sql`
