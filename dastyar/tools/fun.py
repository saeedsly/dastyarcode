"""Fun & small utilities: dice, weather (with no key), currency, jokes, time zones."""
from __future__ import annotations

import json
import random
import urllib.parse
import urllib.request
from typing import Optional

from ..utils import run, truncate
from .base import ToolContext, ToolError, tool

UA = "Dastyar/1.0"


@tool("dice", "یک تاس می‌اندازد (یا چند تاس).", category="سرگرمی",
      params={"count": {"type": "integer"}, "sides": {"type": "integer"}})
def dice(count: int = 1, sides: int = 6, ctx: Optional[ToolContext] = None) -> str:
    count = max(1, min(20, int(count or 1)))
    sides = max(2, min(1000, int(sides or 6)))
    rolls = [random.randint(1, sides) for _ in range(count)]
    return "🎲 %s (جمع: %d)" % ("، ".join(map(str, rolls)), sum(rolls))


@tool("random_pick", "از بین چند گزینه یکی را تصادفی انتخاب می‌کند.", category="سرگرمی",
      params={"options": {"type": "array", "items": {"type": "string"}}},
      required=["options"])
def random_pick(options: list, ctx: Optional[ToolContext] = None) -> str:
    if not options:
        raise ToolError("گزینه‌ها خالی است.")
    return "🎯 انتخاب شد: %s" % random.choice([str(o) for o in options])


JOKES = [
    "به یه برنامه‌نویس گفتن: چرا همیشه عینکت رو می‌زنی؟ گفت: چون بدون عینک نمی‌تونم کد بزنم، با عینک هم نمی‌تونم، ولی حداقل می‌بینمشون! 😄",
    "دو تا بایت داشتن می‌رفتن، یکیشون گفت: من کم‌حافظه‌ام. اون یکی گفت: چی گفتی؟ 😂",
    "چرا برنامه‌نویس‌ها همیشه تاریکی رو دوست دارن؟ چون باگ‌ها فقط تو نور دیده می‌شن! 🌚",
    "یه دیباگر می‌ره کافه، می‌گه: یه قهوه، ولی قبلش یه قهوه بدید تست کنم. ☕",
    "الگوریتم زندگی: اگر مشکل حل نشد، با یک if دیگه امتحان کن! 🙂",
]


@tool("tell_joke", "یک جوک کوتاه تعریف می‌کند.", category="سرگرمی", params={})
def tell_joke(ctx: Optional[ToolContext] = None) -> str:
    return random.choice(JOKES)


INSPIRING = [
    "هر کار بزرگی با یک قدم کوچک شروع می‌شود. امروز همون قدم رو بردار. 🚀",
    "بهترین زمان برای شروع، همین حالاست؛ بقیه‌ش داستان می‌شه. ✨",
    "به جای اینکه کامل باشی، شروع کن. کاملی بعداً میاد. 🌱",
    "تو از چیزی که فکر می‌کنی قوی‌تری. فقط یک روز دیگه ادامه بده. 💪",
]


@tool("inspire_me", "یک جمله‌ی انگیزشی می‌گوید.", category="سرگرمی", params={})
def inspire_me(ctx: Optional[ToolContext] = None) -> str:
    return random.choice(INSPIRING)


@tool(
    "weather",
    "هوای فعلی یک شهر را می‌گوید (بدون کلید API، با Open-Meteo).",
    category="اطلاعات",
    params={"city": {"type": "string"}},
    required=["city"],
)
def weather(city: str = "Tehran", ctx: Optional[ToolContext] = None) -> str:
    try:
        geo_url = "https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&language=fa&format=json" % urllib.parse.quote(city)
        req = urllib.request.Request(geo_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            geo = json.loads(resp.read().decode("utf-8", "replace"))
        results = geo.get("results") or []
        if not results:
            raise ToolError("شهر «%s» پیدا نشد." % city)
        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        name = place.get("name") or city
        country = place.get("country", "")
        url = (
            "https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
            "precipitation,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max&timezone=auto&forecast_days=3" % (lat, lon)
        )
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("دریافت هوا ناموفق بود: %s" % exc)

    codes = {
        0: "صاف ☀️", 1: "تقریباً صاف 🌤️", 2: "نیمه‌ابری ⛅", 3: "ابری ☁️", 45: "مه 🌫️", 48: "مه یخ‌زده 🌫️",
        51: "نم‌نم باران 🌦️", 53: "نم‌نم باران 🌦️", 55: "نم‌نم شدید 🌦️", 61: "باران سبک 🌧️",
        63: "باران متوسط 🌧️", 65: "باران شدید 🌧️", 71: "برف سبک 🌨️", 73: "برف 🌨️", 75: "برف شدید ❄️",
        80: "رگبار 🌦️", 81: "رگبار شدید 🌧️", 82: "رگبار خیلی شدید ⛈️", 95: "رعدوبرق ⛈️", 96: "رعدوبرق با تگرگ ⛈️",
    }
    cur = data.get("current", {})
    daily = data.get("daily", {})
    desc = codes.get(cur.get("weather_code"), "نامشخص")
    lines = [
        "🌍 %s، %s" % (name, country),
        "🌡️ دما: %.1f°C (احساس واقعی %.1f°C)" % (cur.get("temperature_2m", 0), cur.get("apparent_temperature", 0)),
        "☁️ وضعیت: %s" % desc,
        "💧 رطوبت: %s%%" % cur.get("relative_humidity_2m", "-"),
        "💨 باد: %s km/h" % cur.get("wind_speed_10m", "-"),
    ]
    if daily.get("time"):
        lines.append("")
        for i, day in enumerate(daily["time"][:3]):
            lines.append("📅 %s: کمینه %.0f° / بیشینه %.0f° • بارش %s%%" % (
                day,
                (daily.get("temperature_2m_min") or [0])[i],
                (daily.get("temperature_2m_max") or [0])[i],
                (daily.get("precipitation_probability_max") or ["-"])[i],
            ))
    return "\n".join(lines)


@tool(
    "currency_rate",
    "نرخ تبدیل ارزها (دلار، یورو، پوند، تومان...) را با نرخ به‌روز نشان می‌دهد.",
    category="اطلاعات",
    params={
        "base": {"type": "string", "description": "ارز مبنا، مثل USD"},
        "target": {"type": "string", "description": "ارز مقصد، مثل IRT یا EUR"},
        "amount": {"type": "number"},
    },
)
def currency_rate(base: str = "USD", target: str = "EUR", amount: float = 1.0,
                  ctx: Optional[ToolContext] = None) -> str:
    base = (base or "USD").upper()
    target = (target or "EUR").upper()
    if target in ("IRT", "IRR", "TOMAN", "ریال", "تومان"):
        target = "IRR"
    try:
        url = "https://api.frankfurter.app/latest?from=%s&to=%s" % (base, target)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15) as resp:
            data = json.loads(resp.read().decode())
        rate = (data.get("rates") or {}).get(target)
        if rate is None:
            raise ToolError("نرخ %s به %s در دسترس نیست (ارزهای ایران در این API نیستند؛ از web_search استفاده کن)." % (base, target))
        return "💱 %.2f %s = %.2f %s (نرخ %s)" % (amount, base, amount * rate, target, data.get("date"))
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("دریافت نرخ ارز ناموفق بود: %s" % exc)
