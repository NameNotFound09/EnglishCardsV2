from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from data.db_session import global_init, create_session
from data.Banks import Bank
from data.Users import User
from sqlalchemy import orm
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from forms import LoginForm, RegisterForm
import os
from werkzeug.utils import secure_filename
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = '1234567890'
global_init("db/banks.sqlite")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'avatars')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@login_manager.user_loader
def load_user(user_id_):
    db_sess = create_session()
    return db_sess.get(User, user_id_)


@app.route('/')
def index():
    return redirect('/login')


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
        new_bank = Bank(user_id=user.id, bank={})
        db_sess.add(new_bank)
        db_sess.commit()
        flash("Регистрация успешна!", "success")
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/")


@app.route('/main', methods=['GET', 'POST'])
@login_required
def main():
    db_sess = create_session()
    bank_entry = db_sess.query(Bank).filter(Bank.user_id == current_user.id).first()
    user_bank = bank_entry.bank if bank_entry and bank_entry.bank else {}
    words_list = list(user_bank.keys())
    word = None
    if words_list:
        word = random.choice(words_list)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'word_bank':
            return redirect('/words')

        if action == 'button_input_word':
            if len(words_list) < 2:
                flash('Добавьте минимум 2 слова в банк, чтобы начать тренировку!', 'warning')
                return redirect(url_for('main'))

            current_word = request.form.get('current_word')
            user_translation = request.form.get('translation', '').strip().lower()
            correct_translation = user_bank.get(current_word, "").lower()
            if user_translation == correct_translation:
                flash('Правильно!', 'success')
                new_word = random.choice([w for w in words_list if w != current_word])
                return render_template('main.html', word=new_word)
            else:
                flash('Неверно, попробуйте еще раз', 'danger')
                return render_template('main.html', word=current_word)

    return render_template('main.html', word=word)


@app.route('/words', methods=['GET', 'POST'])
@login_required
def words():
    db_sess = create_session()
    user = db_sess.query(Bank).filter(Bank.user_id == current_user.id).first()
    if not user:
        user = Bank(user_id=current_user.id, bank={})
        db_sess.add(user)
        db_sess.commit()
    user_bank = user.bank or {}
    if request.method == 'POST':
        action = request.form.get('action')
        add_word = request.form.get('add_word')
        home = request.form.get('home')
        if add_word:
            new_word = request.form.get('new_word')
            new_translation = request.form.get('new_translation')
            user_bank[new_word] = new_translation
            user.bank = user_bank
            orm.attributes.flag_modified(user, "bank")
            db_sess.commit()
        elif action:
            del user_bank[action]
            user.bank = user_bank
            orm.attributes.flag_modified(user, "bank")
            db_sess.commit()
        elif home:
            return redirect('/main')
    return render_template('words.html', words=user_bank)


@app.route('/update_avatar', methods=['POST'])
@login_required
def update_avatar():
    back = request.referrer or url_for('main')
    if 'avatar_file' not in request.files:
        flash('Файл не выбран', 'danger')
        return redirect(back)
    file = request.files['avatar_file']
    if not file or file.filename == '':
        flash('Файл не выбран', 'danger')
        return redirect(back)
    if allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = secure_filename(f"user_{current_user.id}.{ext}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        db_sess = create_session()
        user = db_sess.get(User, current_user.id)
        user.avatar_path = f"avatars/{filename}"
        db_sess.commit()
        flash('Аватар обновлён!', 'success')
    else:
        flash('Недопустимый формат. Разрешены: JPG, PNG, GIF', 'danger')
    return redirect(back)


@app.route('/delete_avatar', methods=['POST'])
@login_required
def delete_avatar():
    back = request.referrer or url_for('main')
    db_sess = create_session()
    user = db_sess.get(User, current_user.id)
    if user.avatar_path:
        file_path = os.path.join(BASE_DIR, 'static', user.avatar_path)
        if os.path.exists(file_path):
            os.remove(file_path)
        user.avatar_path = None
        db_sess.commit()
        flash('Фото профиля удалено', 'success')
    return redirect(back)


@app.route('/alice', methods=['POST'])
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
    if command in ['отмена', 'стоп', 'отменить'] and state in ['waiting_word_input', 'waiting_translation_input', 'choosing_test_mode']:
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
                ru_words = [w for w, d in words_dict.items() if any(c in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя' for c in d['translation'])]
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
    elif command == 'да, точно очистить':
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
    app.run(host='0.0.0.0', port=port)
