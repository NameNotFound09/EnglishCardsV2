from flask import Flask, render_template, request, redirect, flash, url_for, session, jsonify
from data import db_session
from data.db_session import global_init, create_session
from data.Banks import Bank
from data.Users import User
from sqlalchemy import orm
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from forms import LoginForm, RegisterForm
import os
import logging
from PIL import Image
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = '1234567890'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, "db", "banks.sqlite")
db_session.global_init(db_path)
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'avatars')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
logging.basicConfig(level=logging.INFO, filename="app_activity.log",
                    format="%(asctime)s %(levelname)s %(message)s")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_learning_statistics(bank_data):
    """функция анализа прогресса пользователя для вывода в консоль или логи."""
    if not bank_data:
        return 0, 0
    total = len(bank_data)
    learned = sum(1 for v in bank_data.values() if isinstance(v, dict) and v.get('rating', 0) > 5)
    return total, learned


def filter_words_by_schedule(all_words):
    """Отбирает слова, которые пора повторить согласно интервальному графику."""
    now = datetime.now()
    ready_to_review = []
    for word, data in all_words.items():
        if isinstance(data, dict):
            review_date_str = data.get('next_review')
            if review_date_str:
                review_date = datetime.strptime(review_date_str, "%Y-%m-%d %H:%M")
                if now >= review_date:
                    ready_to_review.append(word)
    return ready_to_review


def apply_advanced_user_settings(user_id, file, config):
    """
    Функция для комплексной настройки профиля.
    Занимается сохранением аватара, генерацией CSS-темы на основе цветов изображения,
    логированием и очисткой дискового пространства пользователя.
    """
    status = {"success": False, "message": "", "path": ""}

    # Внутренняя проверка расширения
    filename = secure_filename(file.filename)
    extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    try:
        # 1. СОЗДАНИЕ ПЕРСОНАЛЬНОЙ ПАПКИ
        user_folder = os.path.join(config['UPLOAD_FOLDER'], f"id_{user_id}")
        if not os.path.exists(user_folder):
            os.makedirs(user_folder)

        for old_file in os.listdir(user_folder):
            file_to_rem = os.path.join(user_folder, old_file)
            if os.path.isfile(file_to_rem):
                os.remove(file_to_rem)

        # 2. СОХРАНЕНИЕ ОРИГИНАЛА
        target_name = f"avatar_current.{extension}"
        final_path = os.path.join(user_folder, target_name)
        file.save(final_path)

        # 3. ГЕНЕРАЦИЯ ФОНОВОГО ДИЗАЙНА
        with Image.open(final_path) as img:
            img_converted = img.convert("RGB")

            # Обрезаем до квадрата для аватара
            w, h = img_converted.size
            min_side = min(w, h)
            left = (w - min_side) / 2
            top = (h - min_side) / 2
            img_square = img_converted.crop((left, top, left + min_side, top + min_side))
            img_square.thumbnail((300, 300))
            img_square.save(final_path)

            # Анализируем цвет для генерации CSS
            small_img = img_converted.resize((1, 1))
            main_rgb = small_img.getpixel((0, 0))
            r, g, b = main_rgb

            # Создаем градиент и акценты для темы
            bg_dark = f"rgb({int(r / 3)}, {int(g / 3)}, {int(b / 3)})"
            accent = f"rgb({r}, {g}, {b})"

        # 4. СОЗДАНИЕ CSS ФАЙЛА ФОНА
        css_filename = "theme_colors.css"
        css_path = os.path.join(user_folder, css_filename)

        style_content = f"""
        /* Автогенерируемая тема пользователя {user_id} */
        body {{
            background: linear-gradient(180deg, {bg_dark} 0%, #121212 100%) !important;
            background-attachment: fixed !important;
        }}
        .main-card {{
            border-top: 4px solid {accent} !important;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5) !important;
        }}
        .btn-success {{
            background-color: {accent} !important;
            border-color: {accent} !important;
            box-shadow: 0 0 15px rgba({r},{g},{b}, 0.4);
        }}
        .profile-img {{
            border: 2px solid {accent} !important;
        }}
        """

        with open(css_path, "w", encoding="utf-8") as f:
            f.write(style_content)

        # 5. ЛОГИРОВАНИЕ ОПЕРАЦИИ
        log_file = os.path.join(user_folder, "upload_history.log")
        with open(log_file, "a", encoding="utf-8") as log:
            log.write(f"[{datetime.now()}] Uploaded {filename}. Dominant color: {accent}\n")

        status["path"] = f"avatars/id_{user_id}/{target_name}"
        status["theme_path"] = f"avatars/id_{user_id}/{css_filename}"
        status["success"] = True
        status["message"] = "Аватар и фоновая тема успешно обновлены"

    except Exception as e:
        status["message"] = f"Ошибка процессора: {str(e)}"

    return status


# --- Функция для расчета интервала в МИНУТАХ ---
def get_next_interval(success, current_rating):
    if not success:
        return 0, 1

    new_rating = current_rating + 1
    # Интервалы в минутах
    new_interval = 2 ** new_rating
    return new_rating, new_interval


# --- Функция добавления готового набора ---
def add_random_set(user_id):
    sets = [
        {"Travel": {"Ticket": "Билет", "Plane": "Самолет", "Passport": "Паспорт"}},
        {"IT": {"Bug": "Ошибка", "Code": "Код", "Array": "Массив"}},
        {"Food": {"Cheese": "Сыр", "Bread": "Хлеб", "Milk": "Молоко"}},
        {"Путешествия": {"Ticket": "Билет", "Airport": "Аэропорт", "Hotel": "Отель"}},
        {"IT & Код": {"Variable": "Переменная", "Loop": "Цикл", "Bug": "Ошибка"}},
        {"Еда": {"Bread": "Хлеб", "Cheese": "Сыр", "Water": "Вода"}},
        {"Семья": {"Mother": "Мать", "Father": "Отец", "Brother": "Брат"}},
        {"Дом": {"Window": "Окно", "Door": "Дверь", "Kitchen": "Кухня"}},
        {"Животные": {"Cat": "Кот", "Dog": "Собака", "Bird": "Птица"}},
        {"Цвета": {"Red": "Красный", "Blue": "Синий", "Green": "Зеленый"}},
        {"Время": {"Minute": "Минута", "Hour": "Час", "Month": "Месяц"}},
        {"Погода": {"Rain": "Дождь", "Sun": "Солнце", "Cloud": "Облако"}},
        {"Чувства": {"Happy": "Счастливый", "Sad": "Грустный", "Angry": "Злой"}},
        {"Работа": {"Boss": "Начальник", "Salary": "Зарплата", "Office": "Офис"}},
        {"Природа": {"Tree": "Дерево", "River": "Река", "Mountain": "Гора"}},
        {"Одежда": {"Shirt": "Рубашка", "Pants": "Брюки", "Shoes": "Обувь"}},
        {"Здоровье": {"Doctor": "Врач", "Health": "Здоровье", "Pain": "Боль"}},
        {"Город": {"Street": "Улица", "Bridge": "Мост", "Park": "Парк"}},
        {"Транспорт": {"Car": "Машина", "Train": "Поезд", "Bicycle": "Велосипед"}},
        {"Образование": {"School": "Школа", "Student": "Студент", "Lesson": "Урок"}},
        {"Фрукты": {"Apple": "Яблоко", "Banana": "Банан", "Orange": "Апельсин"}},
        {"Спорт": {"Goal": "Гол", "Match": "Матч", "Team": "Команда"}},
        {"Эмоции": {"Fear": "Страх", "Love": "Любовь", "Surprise": "Удивление"}},
        {"Бизнес": {"Profit": "Прибыль", "Market": "Рынок", "Client": "Клиент"}},
        {"Интернет": {"Website": "Сайт", "Network": "Сеть", "Password": "Пароль"}},
        {"Покупки": {"Price": "Цена", "Discount": "Скидка", "Bag": "Сумка"}},
        {"Кухня": {"Fork": "Вилка", "Spoon": "Ложка", "Plate": "Тарелка"}},
        {"Тело": {"Head": "Голова", "Hand": "Рука", "Leg": "Нога"}},
        {"Мебель": {"Chair": "Стул", "Table": "Стол", "Bed": "Кровать"}},
        {"Инструменты": {"Hammer": "Молоток", "Saw": "Пила", "Nail": "Гвоздь"}},
        {"Космос": {"Star": "Звезда", "Planet": "Планета", "Moon": "Луна"}},
        {"Профессии": {"Teacher": "Учитель", "Driver": "Водитель", "Artist": "Художник"}},
        {"Музыка": {"Song": "Песня", "Sound": "Звук", "Guitar": "Гитара"}}

    ]
    selected_dict = random.choice(sets)
    set_name = list(selected_dict.keys())[0]
    words_to_add = selected_dict[set_name]

    db_sess = create_session()
    bank_entry = db_sess.query(Bank).filter(Bank.id == user_id).first()

    if not bank_entry:
        bank_entry = Bank(id=user_id, bank={})
        db_sess.add(bank_entry)

    if bank_entry.bank is None:
        bank_entry.bank = {}

    temp_bank = dict(bank_entry.bank)

    for word, trans in words_to_add.items():
        if word not in temp_bank:
            temp_bank[word] = {
                "translation": trans,
                "rating": 0,
                "next_review": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "interval": 1
            }

    bank_entry.bank = temp_bank
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(bank_entry, "bank")
    db_sess.commit()
    return set_name


@app.route('/')
def index():
    return redirect('/register')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/")


@login_manager.user_loader
def load_user(user_id_):
    db_sess = db_session.create_session()
    user = db_sess.get(User, user_id_)
    db_sess.close()
    return user


@app.teardown_appcontext
def shutdown_session(exception=None):
    pass


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/main')
    form = LoginForm()
    if form.validate_on_submit():
        db_sess = create_session()
        user = db_sess.query(User).filter(User.login == form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect("/main")
        else:
            flash('Неверный логин или пароль', 'danger')
    return render_template('login.html', title='Вход', form=form)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect('/main')
    form = RegisterForm()
    if form.validate_on_submit():
        db_sess = create_session()
        if db_sess.query(User).filter(User.login == form.username.data).first():
            flash("Этот логин уже занят", "danger")
            return render_template('register.html', form=form)
        user = User()
        user.login = form.username.data
        user.password = form.password.data
        db_sess.add(user)
        db_sess.flush()
        new_bank = Bank(id=user.id, bank={})
        db_sess.add(new_bank)
        db_sess.commit()
        flash("Регистрация успешна!", "success")
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/main', methods=['GET', 'POST'])
@login_required
def main():
    """
    Основной контроллер главной страницы.
    Включает в себя:
    - Систему интервальных повторений
    - Обработку POST-команд тренажера
    - Динамическое управление сессиями и кэшированием ключей
    - Интеллектуальный подбор слов для тренировки
    """
    try:
        db_sess = create_session()
        bank_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()

        # Обработка действий пользователя до основной логики
        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'word_bank':
                logging.info(f"User {current_user.id} redirected to word bank.")
                return redirect('/words')

            # Логика обработки ответа в тренажере
            if action == 'button_input_word':
                last_word = request.form.get('current_word')
                user_trans = request.form.get('translation', '').strip().lower()

                # Защита от пустых данных в базе
                if not bank_entry or not bank_entry.bank or last_word not in bank_entry.bank:
                    flash("Ошибка данных. Попробуйте обновить страницу.", "danger")
                    return redirect(url_for('main'))

                word_data = bank_entry.bank.get(last_word)
                correct_trans = word_data.get('translation', '').lower()

                if user_trans == correct_trans:
                    flash('Правильно! Прогресс обновлен.', 'success')
                    new_rating, new_interval = get_next_interval(True, word_data.get('rating', 0))
                    word_data['rating'] = new_rating
                    word_data['next_review'] = (datetime.now() + timedelta(minutes=new_interval)).strftime(
                        "%Y-%m-%d %H:%M")

                    logging.info(f"User {current_user.id} answered CORRECTly for '{last_word}'")
                else:
                    flash(f'Неверно! Правильный ответ: {correct_trans}', 'danger')
                    # Сброс интервала при ошибке
                    word_data['rating'] = 0
                    word_data['next_review'] = (datetime.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")

                    logging.warning(f"User {current_user.id} MISSED word '{last_word}'")

                # Принудительное сохранение изменений в JSON поле
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(bank_entry, "bank")
                db_sess.commit()

        # Проверка состояния банка после возможных POST изменений
        if not bank_entry or not bank_entry.bank:
            return render_template('main.html', bank={}, total_count=0, word=None)

        all_words = bank_entry.bank
        all_keys = list(all_words.keys())
        total_count = len(all_keys)

        total, learned = get_learning_statistics(all_words)
        logging.info(f"User {current_user.id} progress: {learned}/{total} words learned.")

        # Управление настройками отображения
        new_count = request.args.get('count', type=int)
        if new_count is not None:
            session['requested_count'] = new_count
            session.pop('selected_keys', None)

        requested_count = session.get('requested_count', 5)
        if 'selected_keys' not in session or not session['selected_keys']:
            if requested_count <= total_count:
                session['selected_keys'] = random.sample(all_keys, requested_count)
            else:
                session['selected_keys'] = all_keys

        selected_keys = session.get('selected_keys', [])

        # Интеллектуальный выбор слова для тренажера
        due_words = filter_words_by_schedule(all_words)
        available_due = [w for w in due_words if w in selected_keys]

        if available_due:
            current_word = random.choice(available_due)
        elif selected_keys:
            current_word = random.choice(selected_keys)
        else:
            current_word = None

        # Формирование финального списка для отображения
        display_items = []
        for k in selected_keys:
            w_info = all_words.get(k)
            if w_info and isinstance(w_info, dict):
                if k == current_word:
                    display_items.append(k)
                else:
                    if hash(k) % 2 == 0:
                        display_items.append(k)
                    else:
                        display_items.append(w_info.get('translation', 'Error'))

        db_sess.close()
        return render_template('main.html',
                               display_items=display_items,
                               total_count=total_count,
                               learned_count=learned,
                               requested_count=requested_count,
                               word=current_word)

    except Exception as e:
        logging.error(f"Critical error: {e}")
        return f"Проблема с базой данных: {e}", 500


@app.route('/words', methods=['GET', 'POST'])
@login_required
def words():
    db_sess = create_session()
    user_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()

    if user_entry.bank is None:
        user_entry.bank = {}

    user_bank = user_entry.bank

    if request.method == 'POST':
        action = request.form.get('action')
        add_word = request.form.get('add_word')
        delete_action = request.form.get('action')
        home = request.form.get('home')

        if add_word:
            new_w = request.form.get('new_word')
            new_t = request.form.get('new_translation')

            user_bank[new_w] = {
                "translation": new_t,
                "rating": 0,
                "next_review": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "interval": 1
            }

            orm.attributes.flag_modified(user_entry, "bank")
            db_sess.commit()

        elif delete_action:
            if delete_action in user_bank:
                del user_bank[delete_action]
                orm.attributes.flag_modified(user_entry, "bank")
                db_sess.commit()

        elif home:
            return redirect('/main')

    return render_template('words.html', words=user_bank)


@app.route('/update_avatar', methods=['POST'])
@login_required
def update_avatar():
    action = request.form.get('settings_action')

    if action == 'upload_photo':
        file = request.files.get('avatar_file')
        if file and file.filename != '':
            result = apply_advanced_user_settings(current_user.id, file, app.config)
            if result["success"]:
                db_sess = create_session()
                user = db_sess.get(User, current_user.id)
                user.avatar_path = result["path"]
                db_sess.commit()
                session['dynamic_theme'] = result["theme_path"]
            success = result["success"]
            message = result["message"]
            flash(message, "success" if success else "danger")
        else:
            flash("Файл не выбран", "danger")

    elif action == 'set_theme':
        theme = request.form.get('theme_val')
        if theme:
            session['user_theme_preset'] = theme
            flash(f"Тема {theme} применена!", "info")

    elif action == 'add_set':
        set_name = add_random_set(current_user.id)
        flash(f"Добавлен набор: {set_name}", "success")

    return redirect(url_for('main'))


# --- Глобальный рейтинг ---
@app.route('/leaderboard')
def leaderboard():
    db_sess = create_session()
    all_banks = db_sess.query(Bank).all()
    data = []
    for b in all_banks:
        u = db_sess.get(User, b.id)
        score = sum(v['rating'] for v in b.bank.values() if isinstance(v, dict))
        data.append({"login": u.login, "score": score})
    return render_template('leaderboard.html', users=sorted(data, key=lambda x: x['score'], reverse=True))


@app.route('/delete_avatar', methods=['POST'])
@login_required
def delete_avatar():
    back = request.referrer or url_for('main')
    db_sess = create_session()
    user = db_sess.get(User, current_user.id)
    if user.avatar_path:
        file_path = os.path.join(basedir, 'static', user.avatar_path)
        if os.path.exists(file_path):
            os.remove(file_path)
        user.avatar_path = None
        db_sess.commit()
        flash('Фото профиля удалено', 'success')
    return redirect(back)


@app.route('/alice', methods=['GET', 'POST'])
def alice_skill():
    try:
        return _alice_skill_handler()
    except Exception as e:
        print(f"Alice skill error: {e}")
        return jsonify({
            'response': {
                'text': "Произошла ошибка. Попробуй ещё раз или скажи 'привет'.",
                'end_session': False
            },
            'version': '1.0'
        })


def _alice_skill_handler():
    req = request.json
    if not req:
        raise ValueError("Empty request")

    user_info = req.get('session', {}).get('user')
    if not user_info:
        return jsonify({
            'response': {
                'text': "Для использования навыка необходимо войти в аккаунт Яндекс.",
                'end_session': True
            },
            'version': req.get('version', '1.0')
        })

    session = create_session()
    alice_user_id = user_info['user_id']
    bank_record = session.query(Bank).filter(Bank.alice_id == alice_user_id).first()

    if not bank_record:
        bank_record = Bank(alice_id=alice_user_id, bank={})
        session.add(bank_record)
        session.commit()

    user_data = bank_record.bank or {}
    command = req['request'].get('command', '').lower().strip()
    original = req['request'].get('original_utterance', '').strip()
    state = user_data.get('state', 'main')
    response_text = ""
    suggested_actions = []

    # Отмена текущего действия (всегда обрабатывается первой)
    if command in ['отмена', 'стоп', 'отменить'] and state in ['waiting_word_input', 'waiting_translation_input',
                                                               'choosing_test_mode']:
        user_data['state'] = 'main'
        user_data.pop('temp_word', None)
        response_text = "Действие отменено. Что будем делать?"

    # --- СНАЧАЛА проверяем состояния (чтобы перевод не спутался с командой) ---

    # Добавление слова — шаг 2: получаем слово, просим перевод
    elif user_data.get('state') == 'waiting_word_input':
        word = original.lower().strip() or command.strip()
        if not word or len(word) > 50:
            response_text = "❌ Некорректное слово. Попробуй ещё раз или скажи 'отмена'."
        else:
            user_data['temp_word'] = word
            user_data['state'] = 'waiting_translation_input'
            response_text = f"Хорошо, слово '{word}'. Теперь скажи его перевод."

    # Добавление слова — шаг 3: получаем перевод, сохраняем
    elif user_data.get('state') == 'waiting_translation_input':
        translation = original.strip() or command.strip()
        word = user_data.pop('temp_word', '')
        if not translation or len(translation) > 100 or not word:
            response_text = "❌ Некорректный перевод. Попробуй ещё раз командой 'новое слово'."
        else:
            words_dict = user_data.get('words', {})
            if word in words_dict:
                response_text = f"⚠️ Слово '{word}' уже есть в словаре. Его перевод: {words_dict[word]['translation']}"
            else:
                words_dict[word] = {
                    'translation': translation,
                    'correct': 0,
                    'attempts': 0,
                    'last_attempt': None,
                    'streak': 0
                }
                user_data['words'] = words_dict
                response_text = f"✅ Слово '{word}' — '{translation}' добавлено!"
        user_data['state'] = 'main'

    # Ответ в режиме английский → русский
    elif user_data.get('state') == 'answering_test':
        current_word = user_data.get('current_test_word')
        words_dict = user_data.get('words', {})
        correct_translation = words_dict[current_word]['translation']
        user_answer = original.strip() or command

        words_dict[current_word]['attempts'] += 1
        if user_answer.lower() == correct_translation.lower():
            words_dict[current_word]['correct'] += 1
            words_dict[current_word]['streak'] += 1
            response_text = "✅ Правильно! Молодец!"
        else:
            words_dict[current_word]['streak'] = 0
            response_text = f"❌ Неверно. Правильный перевод: '{correct_translation}'"

        user_data['words'] = words_dict
        user_data['state'] = 'main'

    # Ответ в режиме русский → английский
    elif user_data.get('state') == 'answering_test_ru_en':
        en_word = user_data.pop('expected_answer', None)
        user_answer = (original.strip() or command).lower()
        words_dict = user_data.get('words', {})

        if en_word and en_word in words_dict:
            words_dict[en_word]['attempts'] += 1
            if user_answer == en_word.lower():
                words_dict[en_word]['correct'] += 1
                words_dict[en_word]['streak'] += 1
                response_text = "✅ Верно! Отлично!"
            else:
                words_dict[en_word]['streak'] = 0
                response_text = f"❌ Неправильно. Правильный ответ: '{en_word}'"
            user_data['words'] = words_dict
        else:
            response_text = "❌ Ошибка системы. Попробуй начать тест заново."
        user_data['state'] = 'main'

    # Выбор режима теста
    elif user_data.get('state') == 'choosing_test_mode':
        if '1' in command or 'английский' in command:
            user_data['test_mode'] = 'en_ru'
            response_text = "Режим: английский → русский. Начни тренировку командой 'тест'."
        elif '2' in command or 'русский' in command:
            user_data['test_mode'] = 'ru_en'
            response_text = "Режим: русский → английский. Начни тренировку командой 'тест'."
        else:
            response_text = "Не понял режим. Выбери 1 или 2."
        user_data['state'] = 'main'

    # --- ПОТОМ проверяем команды ---

    # Приветствие и главное меню
    elif command in ['привет', 'здравствуй', 'start', 'начало', 'запусти', 'приветик', '']:
        user_data['state'] = 'main'
        response_text = (
            "Привет! Я — помощник для изучения английских слов!\n\n"
            "Доступные команды:\n"
            "• 'новое слово' — добавить слово с переводом\n"
            "• 'мои слова' — посмотреть все слова\n"
            "• 'тест' — начать тренировку\n"
            "• 'режим теста' — выбрать тип тренировки\n"
            "• 'удалить слово' — удалить конкретное слово\n"
            "• 'очистить все' — удалить все слова\n"
            "• 'статистика' — посмотреть прогресс\n"
            "• 'помощь' — показать подсказки\n\n"
            "Что будем делать?"
        )
        suggested_actions = [
            {"title": "Новое слово", "hide": True},
            {"title": "Мои слова", "hide": True},
            {"title": "Тест", "hide": True}
        ]

    # Помощь
    elif command == 'помощь':
        response_text = (
            "Команды помощника:\n\n"
            "1. 'новое слово' → добавить слово (два шага: слово, затем перевод)\n"
            "2. 'мои слова' → показать все сохранённые слова\n"
            "3. 'тест' → начать тренировку перевода\n"
            "4. 'режим теста' → выбрать тип тренировки\n"
            "5. 'удалить слово [слово]' → удалить конкретное слово\n"
            "6. 'очистить все' → удалить все слова\n"
            "7. 'статистика' → посмотреть прогресс\n"
            "8. 'совет' → получить рекомендацию\n"
            "9. 'привет' → вернуться в главное меню\n"
            "10. 'отмена' → прервать текущее действие\n\n"
            "Чем могу помочь?"
        )

    # Выбор режима теста — запуск
    elif command == 'режим теста':
        user_data['state'] = 'choosing_test_mode'
        response_text = (
            "Выбери режим тренировки:\n"
            "1. 'английский' — перевод с английского на русский\n"
            "2. 'русский' — перевод с русского на английский"
        )

    # Добавление нового слова — шаг 1
    elif 'новое слово' in command:
        user_data['state'] = 'waiting_word_input'
        response_text = "Скажи слово, которое хочешь добавить."

    # Показать все слова
    elif command == 'мои слова':
        words_dict = user_data.get('words', {})
        if words_dict:
            sorted_words = sorted(words_dict.items())
            words_list = [f"{w} — {d['translation']}" for w, d in sorted_words]
            response_text = f"Твои слова ({len(words_list)}):\n" + "\n".join(words_list[:20])
            if len(words_list) > 20:
                response_text += f"\n... и ещё {len(words_list) - 20} слов."
        else:
            response_text = "У тебя пока нет сохранённых слов. Добавь их командой 'новое слово'."

    # Статистика
    elif command == 'статистика':
        words_dict = user_data.get('words', {})
        total = len(words_dict)
        attempts = sum(d['attempts'] for d in words_dict.values())
        correct = sum(d['correct'] for d in words_dict.values())
        accuracy = (correct / attempts * 100) if attempts > 0 else 0
        streak = max((d['streak'] for d in words_dict.values()), default=0)
        response_text = (
            f"Статистика изучения:\n"
            f"Всего слов: {total}\n"
            f"Правильных ответов: {correct}\n"
            f"Всего попыток: {attempts}\n"
            f"Точность: {accuracy:.1f}%\n"
            f"Лучшая серия: {streak}\n\n"
            "Старайся учить по 5-10 слов в день!"
        )

    # Совет по учёбе
    elif command == 'совет':
        words_dict = user_data.get('words', {})
        total = len(words_dict)
        attempts = sum(d['attempts'] for d in words_dict.values())
        correct = sum(d['correct'] for d in words_dict.values())
        accuracy = (correct / attempts * 100) if attempts > 0 else 0
        if total == 0:
            response_text = "Совет: начни с добавления первых 5-10 слов — это отличная отправная точка!"
        elif total < 10:
            response_text = "Совет: добавь ещё несколько слов, чтобы тренировка была интереснее. Цель — 20-30 слов!"
        elif accuracy < 70:
            response_text = "Совет: сосредоточься на словах с низкой точностью. Повторяй их чаще!"
        else:
            response_text = "Отличный прогресс! Продолжай в том же духе!"

    # Начало тренировки
    elif command == 'тест':
        words_dict = user_data.get('words', {})
        if not words_dict:
            response_text = "Сначала добавь слова командой 'новое слово'."
        else:
            test_mode = user_data.get('test_mode', 'en_ru')
            test_words = list(words_dict.keys())
            if test_mode == 'en_ru':
                current_word = random.choice(test_words)
                user_data['current_test_word'] = current_word
                user_data['state'] = 'answering_test'
                response_text = f"Как переводится слово '{current_word}'?"
            else:
                ru_words = [w for w, d in words_dict.items() if
                            any(c in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя' for c in d['translation'])]
                if ru_words:
                    en_word = random.choice(ru_words)
                    ru_translation = words_dict[en_word]['translation']
                    user_data['expected_answer'] = en_word
                    user_data['state'] = 'answering_test_ru_en'
                    response_text = f"Переведи на английский: '{ru_translation}'?"
                else:
                    response_text = "Недостаточно русских переводов. Добавь слова с русскими переводами."

    # Удаление конкретного слова
    elif command.startswith('удалить слово '):
        word_to_delete = command.replace('удалить слово ', '').strip()
        words_dict = user_data.get('words', {})
        if word_to_delete in words_dict:
            del words_dict[word_to_delete]
            user_data['words'] = words_dict
            response_text = f"Слово '{word_to_delete}' удалено."
        else:
            response_text = f"Слово '{word_to_delete}' не найдено в словаре."

    # Очистка — шаг 1
    elif command == 'очистить все':
        user_data['confirm_clear'] = True
        response_text = "Ты уверен? Скажи 'да, точно очистить' для подтверждения."

    # Очистка — шаг 2: подтверждение
    elif command in ('да, точно очистить', 'да точно очистить'):
        if user_data.get('confirm_clear'):
            user_data['words'] = {}
            user_data['confirm_clear'] = False
            user_data['state'] = 'main'
            response_text = "Все слова удалены."
        else:
            response_text = "Нечего подтверждать. Скажи 'очистить все', чтобы начать удаление."

    # Неизвестная команда
    else:
        response_text = (
            "Не поняла команду. Попробуй:\n"
            "- 'новое слово' — добавить слово\n"
            "- 'мои слова' — посмотреть слова\n"
            "- 'тест' — тренировка\n"
            "- 'помощь' — все команды"
        )

    bank_record.bank = user_data
    orm.attributes.flag_modified(bank_record, "bank")
    session.commit()

    response = {
        'response': {
            'text': response_text,
            'end_session': False
        },
        'version': req['version']
    }

    if suggested_actions:
        response['response']['buttons'] = suggested_actions

    return jsonify(response)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
