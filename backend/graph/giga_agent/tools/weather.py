import os
from typing import List

import aiohttp
import httpx
from pydantic import Field
from langchain_core.tools import tool


OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


def _map_units(units: str) -> tuple[str, str]:
    """
    Преобразует пользовательские единицы измерения из {c|f|k}
    в значения API OpenWeatherMap и возвращает (owm_units, unit_symbol).
    """
    normalized = (units or "c").strip().lower()[:1]
    if normalized == "f":
        return "imperial", "°F"
    if normalized == "k":
        return "standard", "K"
    return "metric", "°C"


def _format_current(data: dict, unit_symbol: str) -> str:
    name = data.get("name", "")
    weather_desc = " ".join([w.get("description", "") for w in data.get("weather", [])])
    main = data.get("main", {})
    wind = data.get("wind", {})
    sys = data.get("sys", {})

    return (
        f"Current weather for {name}:\n"
        f"    Conditions: {weather_desc}\n"
        f"    Now:         {main.get('temp', '')} {unit_symbol}\n"
        f"    High:        {main.get('temp_max', '')} {unit_symbol}\n"
        f"    Low:         {main.get('temp_min', '')} {unit_symbol}\n"
        f"    Pressure:    {main.get('pressure', '')}\n"
        f"    Humidity:    {main.get('humidity', '')}\n"
        f"    FeelsLike:   {main.get('feels_like', '')}\n"
        f"    Wind Speed:  {wind.get('speed', '')}\n"
        f"    Wind Degree: {wind.get('deg', '')}\n"
        f"    Sunrise:     {sys.get('sunrise', '')} Unixtime\n"
        f"    Sunset:      {sys.get('sunset', '')} Unixtime\n"
    )


def _format_forecast(data: dict, unit_symbol: str) -> str:
    city_name = (data.get("city") or {}).get("name", "")
    lines: List[str] = [f"Weather Forecast for {city_name}:"]
    for item in data.get("list", []):
        dt_txt = item.get("dt_txt", "")
        weather_desc = " ".join(
            [
                f"{w.get('main', '')} {w.get('description', '')}"
                for w in item.get("weather", [])
            ]
        ).strip()
        main = item.get("main", {})
        lines.extend(
            [
                f"Date & Time: {dt_txt}",
                f"Conditions:  {weather_desc}",
                f"Temp:        {main.get('temp', '')} {unit_symbol}",
                f"High:        {main.get('temp_max', '')} {unit_symbol}",
                f"Low:         {main.get('temp_min', '')} {unit_symbol}",
                "",
            ]
        )
    return "\n".join(lines) + ("\n" if lines else "")


@tool(parse_docstring=True)
async def weather(city: str, units: str = "c", lang: str = "en") -> str:
    """
    Получает текущую погоду и 5‑дневный прогноз по городу через OpenWeatherMap.
    Требуется переменная окружения `OWM_API_KEY`.

    Args:
        city: Город для получения погоды. Если есть пробел, оберни название в кавычки.
        units: Единицы измерения температуры (c - celsius | f - fahrenheit | k - kelvin). По умолчанию: c
        lang: Язык описаний погоды. По умолчанию: en
    """
    api_key = os.getenv("OWM_API_KEY")
    if not api_key:
        return "Не задан OWM_API_KEY. Установи переменную окружения OWM_API_KEY со своим ключом OpenWeatherMap."

    owm_units, unit_symbol = _map_units(units)

    params = {"q": city, "appid": api_key, "units": owm_units, "lang": lang}
    async with aiohttp.ClientSession() as session:
        # Current weather
        async with session.get(
            OWM_CURRENT_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            current_json = await resp.json()
            if resp.status != 200:
                message = current_json.get("message") or str(current_json)
                return f"Ошибка получения текущей погоды: {message}"

        # Forecast
        async with session.get(
            OWM_FORECAST_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            forecast_json = await resp.json()
            if resp.status != 200:
                message = forecast_json.get("message") or str(forecast_json)
                return f"Ошибка получения прогноза: {message}"

    parts = [
        _format_current(current_json, unit_symbol),
        _format_forecast(forecast_json, unit_symbol),
    ]
    return "".join(parts)


def _weather_code_to_description(weather_code: int, lang: str = "ru") -> str:
    """
    Преобразует код погоды WMO в текстовое описание.
    Использует стандартную классификацию WMO Weather interpretation codes (WW).
    """
    # Базовые коды погоды WMO
    weather_codes = {
        0: {"ru": "Ясно", "en": "Clear sky"},
        1: {"ru": "Преимущественно ясно", "en": "Mainly clear"},
        2: {"ru": "Переменная облачность", "en": "Partly cloudy"},
        3: {"ru": "Пасмурно", "en": "Overcast"},
        45: {"ru": "Туман", "en": "Fog"},
        48: {"ru": "Иней", "en": "Depositing rime fog"},
        51: {"ru": "Легкая морось", "en": "Light drizzle"},
        53: {"ru": "Умеренная морось", "en": "Moderate drizzle"},
        55: {"ru": "Сильная морось", "en": "Dense drizzle"},
        56: {"ru": "Легкая ледяная морось", "en": "Light freezing drizzle"},
        57: {"ru": "Сильная ледяная морось", "en": "Dense freezing drizzle"},
        61: {"ru": "Небольшой дождь", "en": "Slight rain"},
        63: {"ru": "Умеренный дождь", "en": "Moderate rain"},
        65: {"ru": "Сильный дождь", "en": "Heavy rain"},
        66: {"ru": "Легкий ледяной дождь", "en": "Light freezing rain"},
        67: {"ru": "Сильный ледяной дождь", "en": "Heavy freezing rain"},
        71: {"ru": "Небольшой снег", "en": "Slight snow fall"},
        73: {"ru": "Умеренный снег", "en": "Moderate snow fall"},
        75: {"ru": "Сильный снег", "en": "Heavy snow fall"},
        77: {"ru": "Снежные зерна", "en": "Snow grains"},
        80: {"ru": "Небольшой ливень", "en": "Slight rain showers"},
        81: {"ru": "Умеренный ливень", "en": "Moderate rain showers"},
        82: {"ru": "Сильный ливень", "en": "Violent rain showers"},
        85: {"ru": "Небольшой снежный ливень", "en": "Slight snow showers"},
        86: {"ru": "Сильный снежный ливень", "en": "Heavy snow showers"},
        95: {"ru": "Гроза", "en": "Thunderstorm"},
        96: {"ru": "Гроза с градом", "en": "Thunderstorm with slight hail"},
        99: {"ru": "Гроза с сильным градом", "en": "Thunderstorm with heavy hail"},
    }
    
    lang_key = "ru" if lang.startswith("ru") else "en"
    return weather_codes.get(weather_code, {"ru": "Неизвестно", "en": "Unknown"}).get(lang_key, "Unknown")


@tool(parse_docstring=True)
async def weather_openmeteo(city: str, units: str = "c", lang: str = "ru") -> str:
    """
    Получает текущую погоду для города через Open-Meteo API (бесплатный, без ключа).
    Используется как резервный вариант, если основной инструмент погоды недоступен.
    
    Args:
        city: Город для получения погоды. Если есть пробел, оберни название в кавычки.
        units: Единицы измерения температуры (c - celsius | f - fahrenheit | k - kelvin). По умолчанию: c
        lang: Язык описаний погоды. По умолчанию: ru
    """
    try:
        # Сначала получаем координаты города
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Геокодинг
            geo_response = await client.get(
                geocoding_url,
                params={"name": city, "count": 1, "language": lang}
            )
            
            if geo_response.status_code != 200:
                return f"Ошибка получения координат города: HTTP {geo_response.status_code}"
            
            geo_data = geo_response.json()
            
            if not geo_data.get("results"):
                return f"Город '{city}' не найден"
            
            location = geo_data["results"][0]
            lat = location["latitude"]
            lon = location["longitude"]
            city_name = location.get("name", city)
            country = location.get("country", "")
            
            # Получаем погоду
            weather_url = "https://api.open-meteo.com/v1/forecast"
            weather_params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,precipitation",
                "timezone": "auto"
            }
            
            weather_response = await client.get(weather_url, params=weather_params)
            
            if weather_response.status_code != 200:
                return f"Ошибка получения погоды: HTTP {weather_response.status_code}"
            
            weather_data = weather_response.json()
            current = weather_data.get("current", {})
            
            if not current:
                return "Не удалось получить данные о погоде"
            
            # Определяем единицы измерения
            unit_symbol = "°C"
            if units.lower().startswith("f"):
                unit_symbol = "°F"
                temp = current.get("temperature_2m", 0)
                if temp is not None:
                    temp = (temp * 9/5) + 32
            elif units.lower().startswith("k"):
                unit_symbol = "K"
                temp = current.get("temperature_2m", 0)
                if temp is not None:
                    temp = temp + 273.15
            else:
                temp = current.get("temperature_2m")
            
            # Преобразуем код погоды в описание
            weather_code = current.get("weather_code", 0)
            weather_desc = _weather_code_to_description(weather_code, lang)
            
            # Форматируем результат
            result_lines = [
                f"Current weather for {city_name}" + (f", {country}" if country else "") + ":",
                f"    Conditions: {weather_desc}",
                f"    Temperature: {temp} {unit_symbol}" if temp is not None else "    Temperature: N/A",
                f"    Humidity: {current.get('relative_humidity_2m')}%" if current.get('relative_humidity_2m') is not None else "    Humidity: N/A",
                f"    Wind Speed: {current.get('wind_speed_10m')} km/h" if current.get('wind_speed_10m') is not None else "    Wind Speed: N/A",
            ]
            
            if current.get('precipitation') is not None:
                result_lines.append(f"    Precipitation: {current.get('precipitation')} mm")
            
            return "\n".join(result_lines)
            
    except httpx.TimeoutException:
        return f"Таймаут при получении погоды для города '{city}'"
    except httpx.RequestError as e:
        return f"Ошибка сети при получении погоды: {str(e)}"
    except Exception as e:
        return f"Ошибка при получении погоды: {str(e)}"
