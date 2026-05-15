# Sprint 3 Handoff — V2X Channel Layer (ZeroMQ + ETSI CPM Release 2)

Bu doküman yeni chat'in başlangıcı için bağlam yükleyici. CMP794 V2X-Sim projesinin Sprint 3'üne başlıyoruz, Sprint 1-2 bitti ve GitHub'a push edildi.

---

## 1. Proje durumu (Sprint 2 sonu)

Detaylar **GitHub repo'da PROGRESS.md'de**. Çok kısa özet:

- **Repo:** https://github.com/TahaErr/CARLA_IOT (public, main branch, son commit `f77155a`)
- **Local path (Windows):** `C:\Users\TAHA\Desktop\CARLA_0.9.16\PythonAPI\CARLA_IOT\v2x-sim-sprint1\v2x-sim`
- **Conda env:** `v2xsim` (Python 3.10, CARLA 0.9.16, PyTorch 2.11+cu128, Ultralytics 8.4.48)
- **GPU:** RTX 5080 (Blackwell sm_120) + 64 GB RAM
- **OS:** Windows 11

### Hazır olanlar

- Sprint 1: RSU infrastructure (kamera, intersection discovery)
- Sprint 2.1: YOLO26s detector + GPU setup
- Sprint 2.2: Multi-town balanced dataset (19071 frame, Town03+04+05 train, Town10 test, imbalance < 4x)
- Sprint 2.3: Fine-tune + cross-town evaluation

### Detector metrikleri (Sprint 3'te kullanılacak)

| Metrik | Multi-town val | Town10 cross-town |
|---|---|---|
| mAP@50 | 0.757 | 0.534 |
| Precision (mean) | 0.93 | 0.85 |
| Recall (mean) | 0.71 | 0.50 |

**Önemli:** detector "high precision, moderate recall" profilinde. Sprint 3 için iyi bir özellik: CPM'lerde gürültü az, V2X cooperative perception eksik recall'u tamamlayacak.

### Local'de duran ama GitHub'da olmayan dosyalar (gitignore'lu)

- `dataset_multi/` (Town03+04+05 train+val, ~7 GB)
- `dataset_town10_v2/` (Town10 test set, ~1.5 GB)
- `runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt` (~20 MB fine-tuned model)
- `runs/detect/runs/detect/yolo26s_carla_multi-2/weights/last.pt`

Sprint 3 kodu bu fine-tuned model'i yükleyip RSU detection'da kullanacak.

---

## 2. Sprint 3 amacı

V2X channel + message layer'ı kurmak. Üst-üste 4 modül:

1. **CPM encoder/decoder** — ETSI TS 103 324 v2.1.1 Release 2
2. **Latency model** — Coll-Perales et al., IEEE TVT 2022 (`T_e2e = T_proc + T_tx + T_prop + T_queue`)
3. **PDR model** — Thandavarayan et al., IEEE TVT 2020 (`P_success(d, ρ)`)
4. **Edge-compute budget** — proposal §4.4 (per-RSU + aggregate)

Bunların üstüne **ZeroMQ broker** ve **multi-process orchestration** geliyor.

Proposal mapping: §4.2, §4.3.1, §4.3.2, §4.4.

---

## 3. Mimari kararlar (Sprint 2 sonunda alındı)

### Transport: **ZeroMQ**

- Process-isolated: 1 broker + 38 RSU process + N CAV process
- Network-realistic: tezi "production-grade V2X middleware + safety analysis" şeklinde konumlandırır
- Proposal'ın §6 "Future Direction: Real Jetson deployment" maddesi için doğal hazırlık
- Trade-off: asyncio'dan ~7-10 gün daha uzun, ekstra senkronizasyon kodu gerek

**Tekrar değerlendirme noktası:** eğer Sprint 3.5'te orchestration cehennem olursa asyncio'ya fallback edebiliriz. Şu an için ZeroMQ.

### CPM format: **ETSI ASN.1 (asn1tools) + dataclass abstraction**

- Network üzerinden ASN.1 byte-encoded (spec compliance)
- Kod içinde dataclass (kolay debug)
- `cpm.to_bytes()` / `CPM.from_bytes(data)` arabirimi
- Payload size'ı latency formülünde doğru girer (T_tx = f(real bytes), JSON ile farkı 0.5-2 ms)

### Determinism

- Broker'da virtual `sim_time` saati
- Mesaj sırası: `(sim_time, station_id, msg_id)` stable sort
- CARLA sync mode `dt=0.05` zaten deterministik, broker bunu takip eder

### Channel busy ratio (CBR)

- Broker tüm CPM hacmini izler, aktif CBR'yi her tick için hesaplar
- PDR formülünde `ρ` parametresi olarak kullanılır

---

## 4. Sprint 3 modül sırası

Bağımlılık sırası (önce bağımsız modüller, sonra integration):

| # | Modül | Bağımlılık | Tahmini boyut |
|---|---|---|---|
| 1 | CPM encoder/decoder | bağımsız | ~250 satır + ASN.1 spec |
| 2 | Latency model | bağımsız | ~150 satır |
| 3 | PDR model | bağımsız | ~120 satır |
| 4 | Edge-compute budget | bağımsız | ~150 satır |
| 5 | ZeroMQ broker | 1, 2, 3 | ~300 satır |
| 6 | RSU process (publisher) | 1, 5, fine-tuned YOLO | ~250 satır |
| 7 | Stub CAV process (subscriber) | 1, 5 | ~150 satır (Sprint 4'te dolduralacak) |
| 8 | Orchestration script | 5, 6, 7 | ~150 satır |
| 9 | Integration test | hepsi | ~100 satır |

Her modül kendi unit test'i ile gelmeli (Sprint 2'de skip ettiğimiz şey, Sprint 3'te yapacağız çünkü distributed system'de debug zorlaşır).

---

## 5. İlk adım: Modül 1 — CPM encoder/decoder

### Yapılacaklar

1. **ETSI TS 103 324 v2.1.1 ASN.1 dosyalarını indir.** Kaynak:
   - Resmi: https://forge.etsi.org/rep/ITS/asn1/cpm_ts103324
   - Bağımlılıklar (ITS-Container, ITS-CommonDataTypes vb.): https://forge.etsi.org/rep/ITS/asn1
   - `v2x-sim/specs/cpm/` altına koy (gitignore'a EKLEME — bu spec dosyaları tracked olmalı)

2. **`asn1tools` paketini yükle.** `pip install asn1tools` — yaklaşık 200 KB, saf Python.

3. **`v2xsim/cpm.py` modülünü yaz.** İçerik:
   - `@dataclass class CPMObject` — alanlar: `object_id`, `object_class`, `position`, `velocity`, `confidence`, `time_of_measurement`
   - `@dataclass class CPM` — alanlar: `station_id`, `generation_delta_time`, `objects: list[CPMObject]`, `payload_size_bytes` (encoder doldurur)
   - `CPM.encode() -> bytes` — asn1tools ile ASN.1 OER encoding
   - `CPM.decode(data: bytes) -> CPM` — geri parse
   - Object class enum mapping: YOLO26 → ETSI (`vehicle` → `passengerCar`, vb.)

4. **`tests/test_cpm.py`** — round-trip test (encode → decode → equal), nominal payload size kontrolü (200-400 byte aralığında).

### Karar noktaları (yeni chat'in başlangıcında konuşulacak)

- **YOLO 4-class → ETSI sınıfları nasıl map edilecek?** ETSI CPM Release 2 sınıfları daha geniş (passengerCar, heavyVehicle, motorcycle, pedestrian, cyclist, animal, ...). Bizim 4-class'ı genişletir miyiz, yoksa map'leyip kayıt mı düşeriz?
- **VRU cluster encoding?** Proposal §2.2'de "pedestrian (single + cluster), cyclist (single + cluster)" diyor. Cluster encoding ASN.1 spec'te ayrı container. İlk sürümde single mı yapalım, cluster Sprint 3.5'e bırakalım mı?
- **Confidence quantization.** ETSI 0-100 integer, YOLO 0.0-1.0 float. Round mu, floor mu?

Bunlar 30 dakikalık design konuşması, sonra kodlamaya başlanır.

---

## 6. Sprint 3 sonrası ne var

**Sprint 4 (orijinal proposal):** CAV time-aware late-fusion + HDV NHTSA profiles + VRU stochastic walkers + ablation runner. Sprint 3'ün üstüne kurulur.

**Sprint 5-6 (rapor + buffer):** ablation runs, plot generation, demo video, rapor yazımı.

Proposal §7 timeline'da hala 12 hafta hedefliyoruz. Sprint 3 ZeroMQ ile 2.5-3 hafta tahmini.

---

## 7. Yeni chat'in ilk mesajı için talimat

Yeni chat'e geçtiğinde Claude'a bu dokümanı verirken şöyle başla:

> "Aşağıda projemin Sprint 2 sonu durumu ve Sprint 3 planı var. Repo: github.com/TahaErr/CARLA_IOT, son durum PROGRESS.md ve README.md'de detaylı. Sprint 3'ün ilk modülüne (CPM encoder/decoder) başlayacağız. İlk soru: §5'teki 3 karar noktasını (sınıf mapping, VRU cluster, confidence quantization) birlikte değerlendirelim."

Claude muhtemelen önce GitHub repo'yu doğrulamak isteyecek (PROGRESS.md'den son durumu çekmek için). Eğer **TahaErr/CARLA_IOT** GitHub connector'ı project files'da hala attach'liyse, yeni Claude doğrudan okuyabilir. Değilse README.md ve PROGRESS.md'yi manuel paste edebilir veya raw URL'yi mesajda verebilirsin.

Önemli teknik durum hatırlatması: train edilmiş model `runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt` yolunda local'de (push'a gitmedi, gitignore'lu).

---

## 8. Açık dosya hatırlatmaları

- `Proposal_Final.md` — proje workspace dosyaları arasında, yeni chat'te de erişilebilir olmalı
- `PROGRESS.md` — GitHub repo'da, en güncel durum
- `README.md` — GitHub repo'da, end-to-end Sprint 2 kullanım komutları

---

## 9. Son notlar

- **`runs/` klasörü iç içe duplicate.** `16_train_yolo.py`'a fix uygulandı ama eski klasör yapısı `runs\detect\runs\detect\` şeklinde local'de duruyor. Sprint 3'te eğer yeni model train edilirse temiz `runs\detect\` yapısı oluşacak. Eski yapıyı silmeyin — şu anki `best.pt` orada.
- **Git editor'i.** Sprint 2 sonunda vim'e düştük, INSERT modu kafa karıştırıcı. Yeni chat'te commit yapacaksanız `git config --global core.editor notepad` koşturun, sonraki merge commit'leri Notepad açar.
- **CARLA server'ı.** Her yeni terminal session'da yeniden başlatın gerekirse. Bazen Town değiştirme sırasında takılır.
- **PAT.** GitHub push için Personal Access Token gerektiğinde `https://github.com/settings/tokens` üzerinden classic token, sadece `repo` scope ile yenisi alınabilir.

Sprint 3 başlamaya hazır. Yeni chat'te §5'in karar noktalarıyla başla.
