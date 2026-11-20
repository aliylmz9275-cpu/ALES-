# backend/plugins/ — ALES Eklentileri

Bu klasordeki her `.py` dosyasi bir eklentidir. ALES'i **yeniden baslatmadan**
eklenti ekleyip cikarabilirsin:

- **Ekle:** dosyayi bu klasore kopyala -> UI'da `Ayarlar -> EKLENTILER -> Yenile`
  (veya `POST /plugins/reload`).
- **Cikar:** dosyayi sil -> Yenile. ALES eklentinin `on_unload()` fonksiyonunu
  cagirir ve araclarini listeden dusurur.
- **Gecici kapat:** UI'daki anahtar (`POST /plugins/{id}/toggle`). Durum
  `AppData/ALES/plugins.json` dosyasina yazilir, yeniden baslatmada korunur.

`_` ile baslayan dosyalar (`_ornek.py` gibi) **taranmaz** — sablon/yardimci
dosyalari boyle isaretle.

## Minimum eklenti

```python
PLUGIN_API = 1

def register():
    return {
        "id": "selamla",
        "name": "Selamlayici",
        "description": "Verilen isme merhaba der",
        "version": "1.0.0",
        "tools": [{
            "type": "function",
            "function": {
                "name": "plugin_selamla",
                "description": "Verilen isme Turkce selam verir.",
                "parameters": {
                    "type": "object",
                    "properties": {"isim": {"type": "string"}},
                    "required": ["isim"],
                },
            },
        }],
        "handlers": {
            "plugin_selamla": lambda args, progress_cb=None:
                f"Merhaba {args.get('isim', 'dostum')}!",
        },
    }
```

`register()` sozlesmesi:

| alan | zorunlu | aciklama |
|---|---|---|
| `id` | hayir (dosya adi kullanilir) | benzersiz kimlik |
| `name` / `description` / `version` | hayir | UI'da gorunur |
| `tools` | evet (arac eklemek icin) | `main.py` `TOOLS` ile **ayni** OpenAI tool semasi |
| `handlers` | evet | `{"arac_adi": fn}`; `fn(args)` veya `fn(args, progress_cb)` |
| `keywords` | hayir | `tool_router` filtrelemesinde kullanilir |
| `on_load` / `on_unload` | hayir | yuklenme/bosaltilma kancalari |

Handler bir **string** dondurmeli (model onu okuyacak). String degilse ALES
JSON'a cevirir.

## Kurallar ve sinirlar

1. **Cekirdek arac adlari rezervedir.** `delete_path`, `write_file`,
   `run_python_code`, `click_at`, `take_screenshot` ... gibi adlari
   kullanamazsin; o arac **reddedilir** (eklentinin geri kalani yuklenir) ve
   sebebi UI'da `warnings` altinda gorunur. Sebep: bir eklenti cekirdek araci
   gasp edip "dosyayi sil" cagrisini kendine yonlendirebilirdi.
2. **Ayni arac adini iki eklenti tanimlayamaz.** Ikincisi atlanir.
3. **`register()` cokerse** sadece o eklenti yuklenmez; ALES calismaya devam
   eder. Hata UI'da `load_error` olarak gorunur.
4. **Bu bir kum havuzu DEGILDIR.** Eklenti kodu ALES surecinde, tam yetkiyle
   calisir. Bu klasore dosya koymak "ALES'e kod eklemek" ile aynidir.
   Guvenilmeyen kodu buraya koyma — onun yeri `code_act_executor` (ayri
   process + timeout + statik kapi).
5. Uzun suren islerde `progress_cb("mesaj")` cagirirsan kullanici arayuzde
   ilerleme gorur.

## skills/ ile farki

- `plugins/` = **tek dosya**, sadece kod/arac, calisirken tak-cikar.
- `skills/`  = **klasor + SKILL.md**, dokumantasyon tasir, LLM'e "bu isi nasil
  yaparsin" anlatir, calistirilamayan "referans skill" de olabilir.

Ikisinin araclari `get_all_tools()` icinde birlesir; model ikisini ayirt etmez.
