# K-Fit บันทึกฟิตเนส

เว็บหน้าเดียว (HTML/CSS/JS ธรรมดา) ไม่มี backend ไม่มี build step · โฮสต์บน GitHub Pages · ใช้ออฟไลน์ได้ (service worker) · เพิ่มไว้หน้าจอโฮมได้

## ไฟล์
- `index.html` — ทั้งหน้า: กราฟแคลอรี่ (SVG), ค่าเฉลี่ยสัปดาห์/เดือน, น้ำหนัก/เอว, บันทึกออกกำลังกาย, ตารางซ้อมรายสัปดาห์, ฟอร์มบันทึกเอง
- `data.json` — ข้อมูลย่อจาก Apple Health (สร้างด้วย `tools/extract.py`)
- `sw.js` — cache-first, เปลี่ยนชื่อ cache ทุกเวอร์ชัน และลบ cache เก่า
- `manifest.json`, `icons/` — ติดตั้งเป็นแอป
- `robots.txt` + meta `noindex` — ไม่ให้เครื่องมือค้นหาเก็บ

## อัปเดตข้อมูล
```
python3 tools/extract.py /path/to/export.xml /path/to/checkins.db > data.json
```
แล้วเปลี่ยนเลขเวอร์ชันใน `index.html` (VER, ป้าย, changelog) และ `CACHE` ใน `sw.js`

สคริปต์อ่านไฟล์ export อย่างเดียว ไม่แก้ไข · แคลอรี่รายวันนับเฉพาะจาก Apple Watch (กันนับซ้ำ) · การออกกำลังกายที่ซิงก์ซ้ำจากหลายแอปถูกตัดเหลือรายการเดียว (Apple Watch ก่อน)

ข้อมูลที่บันทึกเอง (น้ำหนัก เอว ติ๊กตาราง) เก็บใน localStorage ของเบราว์เซอร์ · สำรอง/นำเข้าเป็น JSON ได้
