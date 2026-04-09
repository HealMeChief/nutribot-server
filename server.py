from flask import Flask, request, jsonify
from google import genai
from google.genai import types
from supabase import create_client
import base64
import json
import jwt  # pip install PyJWT
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ── Конфиги ──────────────────────────────────────────────────────
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY")
SUPABASE_URL    = os.getenv("SUPABASE_URL")
SUPABASE_KEY    = os.getenv("SUPABASE_KEY")

client_ai = genai.Client(api_key=GEMINI_API_KEY)
supabase  = create_client(SUPABASE_URL, SUPABASE_KEY)
MODEL     = "gemini-2.5-flash-lite"

# ── Вспомогательные функции ───────────────────────────────────────

def ask_gemini(system_prompt, user_message, image_base64=None):
    contents = []
    if image_base64:
        contents.append(types.Part.from_bytes(
            data=base64.b64decode(image_base64),
            mime_type="image/jpeg",
        ))
    contents.append(user_message)
    response = client_ai.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            max_output_tokens=2048,
        ),
    )
    try:
        usage = response.usage_metadata
        ask_gemini.request_count = getattr(ask_gemini, 'request_count', 0) + 1
        ask_gemini.total_tokens  = getattr(ask_gemini, 'total_tokens', 0) + usage.total_token_count
        print(f"\n─── Запрос #{ask_gemini.request_count} | "
              f"токены: {usage.prompt_token_count}→{usage.candidates_token_count} | "
              f"всего за сессию: {ask_gemini.total_tokens} ───\n")
    except:
        pass
    return response.text

def get_user_id(req):
    """Достаём user_id из заголовка Authorization"""
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        # Верифицируем токен через Supabase
        user = supabase.auth.get_user(token)
        return user.user.id
    except:
        return None

# ── Рефреш токена ───────────────────────────────────────────────────

@app.route("/refresh", methods=["POST"])
def refresh_token():
    data          = request.json
    refresh_token = data.get("refresh_token", "")
    try:
        result = supabase.auth.refresh_session(refresh_token)
        return jsonify({
            "access_token":  result.session.access_token,
            "refresh_token": result.session.refresh_token,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 401
    
# ── Авторизация ───────────────────────────────────────────────────

@app.route("/register", methods=["POST"])
def register():
    data     = request.json
    email    = data.get("email", "")
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email и пароль обязательны"}), 400

    try:
        result = supabase.auth.sign_up({
            "email": email,
            "password": password,
        })
        if result.user:
            return jsonify({
                "user_id":      result.user.id,
                "access_token": result.session.access_token if result.session else None,
                "message":      "Регистрация успешна"
            })
        return jsonify({"error": "Ошибка регистрации"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/login", methods=["POST"])
def login():
    data     = request.json
    email    = data.get("email", "")
    password = data.get("password", "")

    try:
        result = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
        return jsonify({
            "user_id":      result.user.id,
            "access_token": result.session.access_token,
            "message":      "Вход выполнен"
        })
    except Exception as e:
        return jsonify({"error": "Неверный email или пароль"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            supabase.auth.sign_out()
        except:
            pass
    return jsonify({"message": "Выход выполнен"})

# ── Профиль ───────────────────────────────────────────────────────

@app.route("/profile", methods=["GET"])
def get_profile():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    try:
        result = supabase.table("profiles")\
            .select("*").eq("id", user_id).single().execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/profile", methods=["PUT"])
def update_profile():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data = request.json
    try:
        supabase.table("profiles").update({
            "gender":         data.get("gender"),
            "age":            data.get("age"),
            "height":         data.get("height"),
            "weight":         data.get("weight"),
            "goal":           data.get("goal"),
            "activity_level": data.get("activityLevel"),
            "about_me":       data.get("aboutMe"),
        }).eq("id", user_id).execute()
        return jsonify({"message": "Профиль обновлён"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Еда ───────────────────────────────────────────────────────────

@app.route("/food", methods=["GET"])
def get_food():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    date = request.args.get("date")  # формат: "2024-03-10"
    try:
        query = supabase.table("food_entries")\
            .select("*").eq("user_id", user_id)
        if date:
            query = query.eq("entry_date", date)
        result = query.execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/food", methods=["POST"])
def add_food():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data = request.json
    try:
        supabase.table("food_entries").insert({
            "id":         data.get("id"),
            "user_id":    user_id,
            "name":       data.get("name"),
            "portion":    data.get("portion"),
            "calories":   data.get("calories"),
            "protein":    data.get("protein"),
            "fat":        data.get("fat"),
            "carbs":      data.get("carbs"),
            "meal_type":  data.get("mealType"),
            "entry_date": data.get("date"),
        }).execute()
        return jsonify({"message": "Блюдо добавлено"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/food/<entry_id>", methods=["PUT"])
def update_food(entry_id):
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data = request.json
    try:
        supabase.table("food_entries").update({
            "name":      data.get("name"),
            "portion":   data.get("portion"),
            "calories":  data.get("calories"),
            "protein":   data.get("protein"),
            "fat":       data.get("fat"),
            "carbs":     data.get("carbs"),
            "meal_type": data.get("mealType"),
        }).eq("id", entry_id).eq("user_id", user_id).execute()
        return jsonify({"message": "Блюдо обновлено"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/food/<entry_id>", methods=["DELETE"])
def delete_food(entry_id):
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    try:
        supabase.table("food_entries")\
            .delete().eq("id", entry_id).eq("user_id", user_id).execute()
        return jsonify({"message": "Блюдо удалено"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Вода ──────────────────────────────────────────────────────────

@app.route("/water", methods=["GET"])
def get_water():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    date = request.args.get("date")
    try:
        result = supabase.table("water_logs")\
            .select("*").eq("user_id", user_id)\
            .eq("entry_date", date).execute()
        if result.data:
            return jsonify(result.data[0])
        return jsonify({"amount_ml": 0, "water_history": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/water", methods=["POST"])
def update_water():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data    = request.json
    date    = data.get("date")
    amount  = data.get("amount_ml", 0)
    history = data.get("water_history", [])

    try:
        # upsert — создаёт или обновляет
        supabase.table("water_logs").upsert({
            "user_id":       user_id,
            "entry_date":    date,
            "amount_ml":     amount,
            "water_history": history,
        }).execute()
        return jsonify({"message": "Вода обновлена"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── ИИ эндпоинты (без изменений, только добавлена авторизация) ────

@app.route("/sync/load", methods=["GET"])
def sync_load():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    try:
        # Профиль
        profile_result = supabase.table("profiles")\
            .select("*").eq("id", user_id).single().execute()
        
        # Еда за последние 30 дней
        from datetime import datetime, timedelta
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        food_result = supabase.table("food_entries")\
            .select("*").eq("user_id", user_id)\
            .gte("entry_date", date_from).execute()
        
        # Вода за последние 30 дней
        water_result = supabase.table("water_logs")\
            .select("*").eq("user_id", user_id)\
            .gte("entry_date", date_from).execute()

        return jsonify({
            "profile": profile_result.data,
            "food":    food_result.data,
            "water":   water_result.data,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/estimate_by_name", methods=["POST"])
def estimate_by_name():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data    = request.json
    name    = data.get("name", "")
    portion = data.get("portion", 150)
    system  = (
        "Ты нутрициолог. Отвечай ТОЛЬКО валидным JSON без markdown. "
        "Без пояснений, без ```json. "
        'Формат: {"calories_per_100g":165,"protein_per_100g":31,'
        '"fat_per_100g":3.6,"carbs_per_100g":0}'
    )
    try:
        result = ask_gemini(system, "Продукт: " + name + ". Дай КБЖУ на 100г.")
        clean  = result.replace("```json", "").replace("```", "").strip()
        return jsonify(json.loads(clean))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/estimate_by_photo", methods=["POST"])
def estimate_by_photo():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data         = request.json
    image_base64 = data.get("image_base64", "")
    system = (
        "Ты нутрициолог. Определи блюдо на фото и оцени КБЖУ. "
        "Отвечай ТОЛЬКО валидным JSON без markdown. Без пояснений, без ```json. "
        'Формат: {"name":"Название на русском","portion":300,'
        '"calories":450,"protein":25,"fat":15,"carbs":50}'
    )
    try:
        result = ask_gemini(system, "Что на фото? Оцени КБЖУ.", image_base64)
        clean  = result.replace("```json", "").replace("```", "").strip()
        return jsonify(json.loads(clean))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/analyze_day", methods=["POST"])
def analyze_day():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data    = request.json
    profile = data.get("profile", {})
    entries = data.get("entries", [])
    totals  = data.get("totals", {})
    goals   = data.get("goals", {})

    gender    = "мужчина" if profile.get("gender") == "male" else "женщина"
    goal_map  = {"loss": "похудение", "gain": "набор массы"}
    goal_text = goal_map.get(profile.get("goal", ""), "поддержание веса")
    about_me  = profile.get("aboutMe", "")
    about_line = ("Особенности: " + about_me + "\n") if about_me else ""

    eaten = "\n".join([
        e["name"] + " — " + str(e["calories"]) + " ккал "
        "(Б:" + str(e["protein"]) + " Ж:" + str(e["fat"]) + " У:" + str(e["carbs"]) + "г)"
        for e in entries
    ]) or "Ничего не съедено"

    left_cal     = goals.get("calories", 0) - totals.get("calories", 0)
    left_protein = goals.get("protein",  0) - totals.get("protein",  0)
    left_fat     = goals.get("fat",      0) - totals.get("fat",      0)
    left_carbs   = goals.get("carbs",    0) - totals.get("carbs",    0)

    system = (
        "Ты дружелюбный нутрициолог-ассистент NutriBot. "
        "Анализируй питание коротко и по делу. "
        "Не используй markdown, звёздочки и жирный текст. "
        "Не здоровайся — отвечай сразу по делу. "
        "Предложи 2-3 конкретных блюда для выполнения дневных целей. "
        "Отвечай на русском, 4-6 предложений."
    )
    user = (
        "Профиль: " + gender + ", " +
        str(profile.get("age")) + " лет, " +
        str(profile.get("weight")) + "кг, цель: " + goal_text + ".\n" +
        about_line +
        "\nСъедено сегодня:\n" + eaten + "\n\n" +
        "Итого: " + str(totals.get("calories", 0)) +
        " из " + str(goals.get("calories", 0)) + " ккал\n" +
        "Осталось: " + str(round(left_cal)) + " ккал | " +
        "Б:" + str(round(left_protein)) + "г | " +
        "Ж:" + str(round(left_fat)) + "г | " +
        "У:" + str(round(left_carbs)) + "г\n" +
        "Вода: " + str(totals.get("water", 0)) +
        " из " + str(goals.get("water", 0)) + " мл\n\n" +
        "Что посоветуешь съесть?"
    )
    try:
        result = ask_gemini(system, user)
        return jsonify({"reply": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chat", methods=["POST"])
def chat():
    user_id = get_user_id(request)
    if not user_id:
        return jsonify({"error": "Не авторизован"}), 401

    data    = request.json
    message = data.get("message", "")
    profile = data.get("profile", {})
    totals  = data.get("totals", {})
    goals   = data.get("goals", {})

    gender    = "мужчина" if profile.get("gender") == "male" else "женщина"
    goal_map  = {"loss": "похудение", "gain": "набор массы"}
    goal_text = goal_map.get(profile.get("goal", ""), "поддержание веса")
    about_me  = profile.get("aboutMe", "")
    about_line = ("- Особенности: " + about_me) if about_me else ""

    system = (
        "Ты NutriBot — умный ассистент по питанию. "
        "Отвечай кратко, дружелюбно, на русском языке. "
        "Не используй markdown, звёздочки, решётки и жирный текст. "
        "Никогда не здоровайся и не представляйся повторно. "
        "Отвечай сразу по делу.\n"
        "Данные пользователя:\n"
        "- " + gender + ", " + str(profile.get("age")) + " лет, " +
        str(profile.get("weight")) + "кг\n"
        "- Цель: " + goal_text + "\n"
        "- Норма: " + str(goals.get("calories")) + " ккал, "
        "Б:" + str(goals.get("protein")) + " "
        "Ж:" + str(goals.get("fat")) + " "
        "У:" + str(goals.get("carbs")) + "г\n"
        "- Съедено: " + str(totals.get("calories")) + " ккал, "
        "Б:" + str(totals.get("protein")) + " "
        "Ж:" + str(totals.get("fat")) + " "
        "У:" + str(totals.get("carbs")) + "г\n"
        "- Вода: " + str(totals.get("water", 0)) +
        " из " + str(goals.get("water", 0)) + " мл\n" +
        about_line
    )
    try:
        result = ask_gemini(system, message)
        return jsonify({"reply": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)