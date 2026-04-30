from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import pandas as pd
import io
from catboost import CatBoostRegressor
import numpy as np

from database import SessionLocal, engine, Base
from models import StudentData, ForecastData, ForecastMeta
from schemas import StudentDataResponse, StudentDataCreate
import logging
import hashlib
from pathlib import Path
import re
import importlib.util
import uuid

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Константы
PROCESS_NAMES = {
    "admission": "Приём",
    "transfers_in": "Переводы",
    "expelled": "Отчисления",
    "academic_leave": "Академ",
    "restored": "Восстановление"
}
REQUIRED_DATA_COLUMNS = ["year", "course", "admission", "transfers_in", "expelled", "academic_leave", "restored"]
SCRIPTS_DIR = Path(__file__).resolve().parent / "source_scripts"
SCRIPTS_DIR.mkdir(exist_ok=True)

# Создаем таблицы
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Student Forecast API")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
async def root():
    return {"message": "Student Forecast API"}


@app.post("/api/upload", response_model=dict)
async def upload_csv(file: UploadFile = File(...)):
    """
    Загружает CSV файл и импортирует данные в базу данных
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате CSV")
    
    try:
        contents = await file.read()
        df = pd.read_csv(io.StringIO(contents.decode('utf-8')))

        df = validate_and_normalize_data_frame(df)
        db = next(get_db())
        records_added = save_student_data_frame(db, df)
        return {
            "message": "Данные успешно загружены",
            "records_added": records_added
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при обработке файла: {str(e)}")


def validate_and_normalize_data_frame(df: pd.DataFrame) -> pd.DataFrame:
    if not all(col in df.columns for col in REQUIRED_DATA_COLUMNS):
        raise HTTPException(
            status_code=400,
            detail=f"Данные должны содержать колонки: {', '.join(REQUIRED_DATA_COLUMNS)}"
        )
    normalized = df[REQUIRED_DATA_COLUMNS].copy()
    for col in REQUIRED_DATA_COLUMNS:
        normalized[col] = pd.to_numeric(normalized[col], errors="raise")
    normalized = normalized.fillna(0)
    for col in REQUIRED_DATA_COLUMNS:
        normalized[col] = normalized[col].astype(int)
    if (normalized[["year", "course"]] <= 0).any().any():
        raise HTTPException(status_code=400, detail="Поля year и course должны быть положительными.")
    return normalized


def save_student_data_frame(db, df: pd.DataFrame) -> int:
    for _, row in df.iterrows():
        db.query(StudentData).filter(
            StudentData.year == int(row["year"]),
            StudentData.course == int(row["course"])
        ).delete()
    records_added = 0
    for _, row in df.iterrows():
        student_data = StudentData(
            year=int(row["year"]),
            course=int(row["course"]),
            admission=int(row["admission"]),
            transfers_in=int(row["transfers_in"]),
            expelled=int(row["expelled"]),
            academic_leave=int(row["academic_leave"]),
            restored=int(row["restored"])
        )
        db.add(student_data)
        records_added += 1
    db.commit()
    return records_added


def sanitize_script_filename(filename: str) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="Пустое имя файла.")
    clean_name = Path(filename).name
    if not clean_name.endswith(".py"):
        raise HTTPException(status_code=400, detail="Поддерживаются только Python скрипты (.py).")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.py", clean_name):
        raise HTTPException(status_code=400, detail="Недопустимое имя скрипта.")
    return clean_name


@app.get("/api/source-scripts")
async def list_source_scripts():
    scripts = []
    for p in sorted(SCRIPTS_DIR.glob("*.py")):
        stat = p.stat()
        scripts.append({
            "name": p.name,
            "size": stat.st_size,
            "updated_at": stat.st_mtime
        })
    return {"scripts": scripts}


@app.post("/api/source-scripts")
async def upload_source_script(file: UploadFile = File(...)):
    script_name = sanitize_script_filename(file.filename or "")
    content = await file.read()
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Скрипт должен быть в UTF-8.")
    if "def main" not in decoded:
        raise HTTPException(status_code=400, detail="В скрипте должна быть функция main().")
    target = SCRIPTS_DIR / script_name
    target.write_text(decoded, encoding="utf-8")
    return {"message": "Скрипт загружен", "name": script_name}


@app.delete("/api/source-scripts/{script_name}")
async def delete_source_script(script_name: str):
    clean_name = sanitize_script_filename(script_name)
    target = SCRIPTS_DIR / clean_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Скрипт не найден.")
    target.unlink()
    return {"message": "Скрипт удален", "name": clean_name}


@app.post("/api/source-scripts/{script_name}/run")
async def run_source_script(script_name: str):
    clean_name = sanitize_script_filename(script_name)
    target = SCRIPTS_DIR / clean_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Скрипт не найден.")

    module_name = f"source_script_{target.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=400, detail="Не удалось загрузить скрипт.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка выполнения скрипта: {str(e)}")

    main_fn = getattr(module, "main", None)
    if main_fn is None or not callable(main_fn):
        raise HTTPException(status_code=400, detail="Скрипт должен содержать вызываемую функцию main().")

    try:
        result = main_fn()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка в main(): {str(e)}")

    if isinstance(result, dict) and "data" in result:
        rows = result["data"]
    else:
        rows = result
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="main() должен вернуть список записей или объект {data: [...]} .")
    if not rows:
        raise HTTPException(status_code=400, detail="main() вернул пустой набор данных.")

    try:
        df = pd.DataFrame(rows)
        df = validate_and_normalize_data_frame(df)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Некорректный формат данных из скрипта: {str(e)}")

    db = next(get_db())
    records_added = save_student_data_frame(db, df)
    return {
        "message": "Данные загружены из скрипта",
        "script": clean_name,
        "records_added": records_added
    }


@app.get("/api/data", response_model=List[StudentDataResponse])
async def get_data():
    """
    Получает все загруженные данные
    """
    db = next(get_db())
    data = db.query(StudentData).order_by(StudentData.year, StudentData.course).all()
    return data


@app.delete("/api/data")
async def delete_all_data():
    """
    Удаляет все данные из базы
    """
    db = next(get_db())
    db.query(StudentData).delete()
    db.commit()
    return {"message": "Все данные удалены"}


@app.get("/api/forecast")
async def get_forecast(periods: int = 5, force: bool = False):
    """
    Строит прогноз на основе CatBoost + динамической цепи Маркова
    """
    db = next(get_db())
    data = db.query(StudentData).order_by(StudentData.year, StudentData.course).all()
    
    if not data:
        raise HTTPException(status_code=400, detail="Нет данных для прогнозирования. Загрузите данные сначала.")
    
    # Вычисляем hash данных
    data_hash = compute_data_hash(db)
    
    # Проверяем, есть ли актуальный сохраненный прогноз (если не force)
    if not force:
        meta = db.query(ForecastMeta).first()
        if meta and meta.data_hash == data_hash:
            logging.info("Загружаем сохраненный прогноз из БД")
            forecasts = load_forecast_from_db(db)
            if forecasts:
                return forecasts
    
    # Логируем количество загруженных записей
    logging.info(f"Загружено записей для прогноза: {len(data)}")
    
    # Преобразуем данные в DataFrame
    records = []
    for item in data:
        records.append({
            'year': item.year,
            'course': item.course,
            'admission': item.admission,
            'transfers_in': item.transfers_in,
            'expelled': item.expelled,
            'academic_leave': item.academic_leave,
            'restored': item.restored
        })
    
    df = pd.DataFrame(records)
    
    # Проверяем, что DataFrame не пуст
    if df.empty:
        raise HTTPException(status_code=400, detail="DataFrame пуст после загрузки данных из базы")
    
    # Проверяем наличие необходимых колонок
    required_cols = ['year', 'course', 'admission', 'transfers_in', 'expelled', 'academic_leave', 'restored']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise HTTPException(status_code=500, detail=f"Отсутствуют колонки в DataFrame: {missing_cols}")
    
    forecasts = build_markov_catboost_forecast(df, periods)
    
    # Проверяем, есть ли хотя бы один прогноз
    has_forecasts = any(
        course_data for course_data in forecasts.values() 
        if course_data and len(course_data) > 0
    )
    
    if not has_forecasts:
        # Собираем информацию для более детального сообщения об ошибке
        courses_with_data = df["course"].unique()
        years_with_data = sorted(df["year"].unique())
        error_detail = (
            f"Не удалось построить прогноз. "
            f"Данные загружены за {len(years_with_data)} лет ({min(years_with_data)}-{max(years_with_data)}), "
            f"для курсов: {sorted(courses_with_data)}. "
            f"Убедитесь, что для хотя бы одного курса и процесса есть данные минимум за 2 года с ненулевыми значениями."
        )
        logging.error(error_detail)
        raise HTTPException(status_code=400, detail=error_detail)
    
    total_forecasts = sum(len(c) for c in forecasts.values())
    logging.info(f"Успешно построено прогнозов для {total_forecasts} комбинаций курс/процесс")
    
    # Сохраняем прогноз в базу данных
    save_forecast_to_db(db, forecasts, data_hash, periods)
    
    return forecasts


def normalize_probabilities(pass_p: float, stay_p: float, exp_p: float, acad_p: float, grad_p: float) -> dict:
    probs = np.array([pass_p, stay_p, exp_p, acad_p, grad_p], dtype=float)
    probs = np.clip(probs, 0.0, 1.0)
    s = float(probs.sum())
    if s <= 0:
        probs = np.array([0.6, 0.2, 0.1, 0.1, 0.0], dtype=float)
        s = float(probs.sum())
    probs = probs / s
    return {
        "pass": float(probs[0]),
        "stay": float(probs[1]),
        "exp": float(probs[2]),
        "acad": float(probs[3]),
        "grad": float(probs[4]),
    }


def constrain_probabilities_for_course(probs: dict, course: int) -> dict:
    """Ограничивает вероятности в реалистичных коридорах для устойчивости прогноза."""
    p_pass = probs["pass"]
    p_stay = probs["stay"]
    p_exp = probs["exp"]
    p_acad = probs["acad"]
    p_grad = probs["grad"]

    if course < 4:
        p_grad = 0.0
        p_pass = float(np.clip(p_pass, 0.70, 0.94))
        p_stay = float(np.clip(p_stay, 0.04, 0.20))
        p_exp = float(np.clip(p_exp, 0.004, 0.08))
        p_acad = float(np.clip(p_acad, 0.003, 0.04))
    else:
        p_pass = 0.0
        p_grad = float(np.clip(p_grad, 0.50, 0.90))
        p_stay = float(np.clip(p_stay, 0.03, 0.18))
        p_exp = float(np.clip(p_exp, 0.004, 0.08))
        p_acad = float(np.clip(p_acad, 0.003, 0.04))

    constrained = normalize_probabilities(p_pass, p_stay, p_exp, p_acad, p_grad)
    if course < 4:
        constrained["grad"] = 0.0
        constrained = normalize_probabilities(
            constrained["pass"],
            constrained["stay"],
            constrained["exp"],
            constrained["acad"],
            0.0
        )
    return constrained


def estimate_recent_growth(values: list[float], max_abs_growth: float = 0.08) -> float:
    """Оценивает средний рост последних лет с ограничением выбросов."""
    if len(values) < 2:
        return 0.0
    rates = []
    start_idx = max(1, len(values) - 4)
    for i in range(start_idx, len(values)):
        prev = max(1.0, float(values[i - 1]))
        cur = float(values[i])
        rates.append((cur - prev) / prev)
    if not rates:
        return 0.0
    growth = float(np.mean(rates))
    return float(np.clip(growth, -max_abs_growth, max_abs_growth))


def estimate_observed_probabilities(row: pd.Series, is_graduation_course: bool) -> dict:
    base = max(
        1.0,
        float(row["admission"] + row["transfers_in"] + row["expelled"] + row["academic_leave"] + row["restored"])
    )
    exp_p = float(row["expelled"]) / base
    acad_p = float(row["academic_leave"]) / base
    stay_p = min(0.5, float(row["restored"]) / base)
    grad_p = max(0.0, 0.35 - exp_p - acad_p) if is_graduation_course else 0.0
    pass_p = max(0.0, 1.0 - (stay_p + exp_p + acad_p + grad_p))
    if is_graduation_course:
        pass_p = 0.0
    return normalize_probabilities(pass_p, stay_p, exp_p, acad_p, grad_p)


def train_catboost_regressor(x: pd.DataFrame, y: pd.Series):
    if len(x) < 3 or y.nunique() <= 1:
        return None
    model = CatBoostRegressor(
        loss_function="RMSE",
        iterations=300,
        depth=6,
        learning_rate=0.05,
        verbose=False,
        random_seed=42
    )
    model.fit(x, y)
    return model


def build_probability_models(df: pd.DataFrame):
    feature_rows = []
    targets = {"pass": [], "stay": [], "exp": [], "acad": [], "grad": []}

    for course in [1, 2, 3, 4]:
        cdf = df[df["course"] == course].sort_values("year").reset_index(drop=True)
        for i in range(1, len(cdf)):
            prev_row = cdf.iloc[i - 1]
            row = cdf.iloc[i]
            probs = estimate_observed_probabilities(row, is_graduation_course=(course == 4))
            feature_rows.append({
                "year": int(row["year"]),
                "course": int(course),
                "admission_prev": float(prev_row["admission"]),
                "transfers_prev": float(prev_row["transfers_in"]),
                "expelled_prev": float(prev_row["expelled"]),
                "academic_prev": float(prev_row["academic_leave"]),
                "restored_prev": float(prev_row["restored"]),
            })
            for k in targets:
                targets[k].append(probs[k])

    if not feature_rows:
        return None, None

    x = pd.DataFrame(feature_rows)
    models = {}
    for key in targets:
        y = pd.Series(targets[key])
        models[key] = train_catboost_regressor(x, y)
    return models, x


def predict_probabilities(models: dict, feature_row: dict, default_probs: dict, is_graduation_course: bool):
    x_pred = pd.DataFrame([feature_row])
    preds = {}
    for key in ["pass", "stay", "exp", "acad", "grad"]:
        model = models.get(key)
        if model is None:
            preds[key] = float(default_probs[key])
        else:
            preds[key] = float(model.predict(x_pred)[0])
    if not is_graduation_course:
        preds["grad"] = 0.0
    if is_graduation_course:
        preds["pass"] = 0.0

    # Сглаживаем CatBoost-предсказание с базовыми вероятностями, чтобы
    # избежать резких скачков на длинном горизонте.
    blend = {}
    for key in ["pass", "stay", "exp", "acad", "grad"]:
        blend[key] = 0.55 * float(default_probs[key]) + 0.45 * float(preds[key])
    normalized = normalize_probabilities(blend["pass"], blend["stay"], blend["exp"], blend["acad"], blend["grad"])
    course = int(feature_row["course"])
    return constrain_probabilities_for_course(normalized, course)


def initialize_state_from_history(df: pd.DataFrame) -> dict:
    """Оценивает стартовый вектор V(t) по историческому набору/переходам."""
    years = sorted(df["year"].unique())
    if not years:
        return {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}

    max_year = int(years[-1])
    course1 = df[df["course"] == 1].set_index("year").sort_index()

    def adm(year: int) -> float:
        if year in course1.index:
            return float(course1.loc[year, "admission"])
        if len(course1) > 0:
            return float(course1["admission"].iloc[-1])
        return 1.0

    # Базовая оценка: курс c в текущем году примерно равен набору 1 курса
    # прошлых лет с естественным коэффициентом удержания.
    state = {
        1: max(1.0, adm(max_year)),
        2: max(1.0, adm(max_year - 1) * 0.93),
        3: max(1.0, adm(max_year - 2) * 0.88),
        4: max(1.0, adm(max_year - 3) * 0.82),
    }
    return state


def forecast_external_processes(df: pd.DataFrame, periods: int):
    forecasts = {course: {"admission": {}, "transfers_in": {}, "restored": {}} for course in [1, 2, 3, 4]}
    max_year = int(df["year"].max())

    for course in [1, 2, 3, 4]:
        cdf = df[df["course"] == course].sort_values("year").reset_index(drop=True)
        for process_key in ["admission", "transfers_in", "restored"]:
            hist = {int(r["year"]): float(r[process_key]) for _, r in cdf.iterrows()}
            if len(cdf) < 2:
                last_val = float(cdf[process_key].iloc[-1]) if len(cdf) == 1 else 0.0
                for y in range(max_year + 1, max_year + periods + 1):
                    hist[y] = max(0.0, last_val)
                forecasts[course][process_key] = hist
                continue

            x_rows = []
            y_rows = []
            for i in range(1, len(cdf)):
                prev = cdf.iloc[i - 1]
                cur = cdf.iloc[i]
                x_rows.append({
                    "year": int(cur["year"]),
                    "course": int(course),
                    f"{process_key}_prev": float(prev[process_key]),
                })
                y_rows.append(float(cur[process_key]))
            x_train = pd.DataFrame(x_rows)
            y_train = pd.Series(y_rows)
            model = train_catboost_regressor(x_train, y_train)
            prev_val = float(cdf.iloc[-1][process_key])
            history_values = [float(v) for v in cdf[process_key].tolist()]
            if process_key == "admission":
                trend_growth = estimate_recent_growth(history_values, max_abs_growth=0.05)
            elif process_key == "transfers_in":
                trend_growth = estimate_recent_growth(history_values, max_abs_growth=0.12)
            else:
                trend_growth = estimate_recent_growth(history_values, max_abs_growth=0.10)
            for y in range(max_year + 1, max_year + periods + 1):
                if model is None:
                    model_pred = prev_val
                else:
                    model_pred = float(model.predict(pd.DataFrame([{
                        "year": y,
                        "course": int(course),
                        f"{process_key}_prev": prev_val,
                    }]))[0])
                trend_pred = prev_val * (1.0 + trend_growth)
                # Для притока важно не терять тренд: даем тренду больший вес.
                pred = 0.35 * model_pred + 0.65 * trend_pred
                # Предотвращаем резкий обвал внешнего притока год-к-году.
                if process_key in {"admission", "transfers_in"}:
                    lower_bound = prev_val * 0.97
                    pred = max(lower_bound, pred)
                pred = max(0.0, pred)
                hist[y] = pred
                prev_val = pred
            forecasts[course][process_key] = hist

    return forecasts


def build_markov_catboost_forecast(df: pd.DataFrame, periods: int) -> dict:
    min_year = int(df["year"].min())
    max_year = int(df["year"].max())
    all_years = list(range(min_year, max_year + periods + 1))

    probability_models, _ = build_probability_models(df)
    external_forecast = forecast_external_processes(df, periods)

    default_probs = {}
    for course in [1, 2, 3, 4]:
        cdf = df[df["course"] == course].sort_values("year")
        if cdf.empty:
            default_probs[course] = normalize_probabilities(0.6, 0.2, 0.1, 0.1, 0.0 if course < 4 else 0.2)
        else:
            default_probs[course] = estimate_observed_probabilities(cdf.iloc[-1], is_graduation_course=(course == 4))

    estimated_population = initialize_state_from_history(df)

    future_probs = {course: {} for course in [1, 2, 3, 4]}
    for year in range(max_year + 1, max_year + periods + 1):
        for course in [1, 2, 3, 4]:
            feature_row = {
                "year": year,
                "course": course,
                "admission_prev": external_forecast[course]["admission"].get(year - 1, 0.0),
                "transfers_prev": external_forecast[course]["transfers_in"].get(year - 1, 0.0),
                "expelled_prev": max(0.0, estimated_population[course] * default_probs[course]["exp"]),
                "academic_prev": max(0.0, estimated_population[course] * default_probs[course]["acad"]),
                "restored_prev": external_forecast[course]["restored"].get(year - 1, 0.0),
            }
            probs = predict_probabilities(
                probability_models or {},
                feature_row,
                default_probs[course],
                is_graduation_course=(course == 4)
            )
            future_probs[course][year] = probs

    expelled_forecast = {course: {} for course in [1, 2, 3, 4]}
    academic_forecast = {course: {} for course in [1, 2, 3, 4]}
    state = {course: float(estimated_population[course]) for course in [1, 2, 3, 4]}

    for year in range(max_year + 1, max_year + periods + 1):
        stays = {}
        passes = {}
        for course in [1, 2, 3, 4]:
            probs = future_probs[course][year]
            n = state[course]
            stays[course] = n * probs["stay"]
            passes[course] = n * probs["pass"]
            # Ограничиваем отток сверху как долю от текущего контингента курса,
            # чтобы исключить нереалистичный взрыв по "отчислениям" и "академу".
            expelled_forecast[course][year] = min(n * probs["exp"], n * 0.065)
            academic_forecast[course][year] = min(n * probs["acad"], n * 0.035)

        next_state = {}
        next_state[1] = (
            external_forecast[1]["admission"].get(year, 0.0)
            + external_forecast[1]["transfers_in"].get(year, 0.0)
            + external_forecast[1]["restored"].get(year, 0.0)
            + stays[1]
        )
        for course in [2, 3, 4]:
            next_state[course] = (
                passes[course - 1]
                + external_forecast[course]["transfers_in"].get(year, 0.0)
                + external_forecast[course]["restored"].get(year, 0.0)
                + stays[course]
            )
        # Предотвращаем искусственное схлопывание курса за один шаг.
        state = {
            c: max(estimated_population[c] * 0.35, next_state[c]) for c in [1, 2, 3, 4]
        }

    forecasts = {course: {} for course in [1, 2, 3, 4]}
    for course in [1, 2, 3, 4]:
        hist = df[df["course"] == course].set_index("year")
        for process_key, process_name in PROCESS_NAMES.items():
            series = []
            for year in all_years:
                if year <= max_year and year in hist.index:
                    yhat = float(hist.loc[year, process_key])
                else:
                    if process_key == "admission":
                        yhat = float(external_forecast[course]["admission"].get(year, 0.0))
                    elif process_key == "transfers_in":
                        yhat = float(external_forecast[course]["transfers_in"].get(year, 0.0))
                    elif process_key == "restored":
                        yhat = float(external_forecast[course]["restored"].get(year, 0.0))
                    elif process_key == "expelled":
                        yhat = float(expelled_forecast[course].get(year, 0.0))
                    else:
                        yhat = float(academic_forecast[course].get(year, 0.0))
                yhat = max(0.0, round(yhat, 2))
                if year <= max_year:
                    yhat_lower = yhat
                    yhat_upper = yhat
                else:
                    spread = max(1.0, yhat * 0.15)
                    yhat_lower = max(0.0, round(yhat - spread, 2))
                    yhat_upper = round(yhat + spread, 2)
                series.append({
                    "ds": f"{year}-01-01",
                    "year": int(year),
                    "yhat": yhat,
                    "yhat_lower": yhat_lower,
                    "yhat_upper": yhat_upper
                })
            forecasts[course][process_key] = {
                "name": process_name,
                "data": series
            }
    return forecasts


def compute_data_hash(db) -> str:
    """Вычисляет hash данных для проверки актуальности прогноза"""
    data = db.query(StudentData).order_by(StudentData.year, StudentData.course).all()
    if not data:
        return ""
    
    # Создаем строку из всех данных
    data_str = ""
    for item in data:
        data_str += f"{item.year}:{item.course}:{item.admission}:{item.transfers_in}:{item.expelled}:{item.academic_leave}:{item.restored}|"
    
    return hashlib.sha256(data_str.encode()).hexdigest()


def save_forecast_to_db(db, forecasts: dict, data_hash: str, periods: int):
    """Сохраняет прогноз в базу данных"""
    try:
        # Удаляем старые прогнозы
        db.query(ForecastData).delete()
        db.query(ForecastMeta).delete()
        
        # Сохраняем метаданные
        meta = ForecastMeta(data_hash=data_hash, periods=periods)
        db.add(meta)
        
        # Сохраняем данные прогноза
        for course, processes in forecasts.items():
            for process_key, process_data in processes.items():
                for item in process_data["data"]:
                    forecast_item = ForecastData(
                        course=int(course),
                        process=process_key,
                        year=item["year"],
                        yhat=item["yhat"],
                        yhat_lower=item["yhat_lower"],
                        yhat_upper=item["yhat_upper"]
                    )
                    db.add(forecast_item)
        
        db.commit()
        logging.info("Прогноз сохранен в базу данных")
    except Exception as e:
        logging.error(f"Ошибка при сохранении прогноза: {str(e)}")
        db.rollback()


def load_forecast_from_db(db) -> dict:
    """Загружает сохраненный прогноз из базы данных"""
    forecasts = {}
    data = db.query(ForecastData).order_by(ForecastData.course, ForecastData.process, ForecastData.year).all()
    
    for item in data:
        course = item.course
        process = item.process
        
        if course not in forecasts:
            forecasts[course] = {}
        
        if process not in forecasts[course]:
            forecasts[course][process] = {
                "name": PROCESS_NAMES.get(process, process),
                "data": []
            }
        
        forecasts[course][process]["data"].append({
            "ds": f"{item.year}-01-01",
            "year": item.year,
            "yhat": item.yhat,
            "yhat_lower": item.yhat_lower,
            "yhat_upper": item.yhat_upper
        })
    
    return forecasts


@app.get("/api/forecast/saved")
async def get_saved_forecast():
    """
    Возвращает сохраненный прогноз, если он актуален
    """
    db = next(get_db())
    
    # Проверяем, есть ли сохраненный прогноз
    meta = db.query(ForecastMeta).first()
    if not meta:
        return {"status": "not_found", "message": "Прогноз не найден"}
    
    # Проверяем актуальность прогноза
    current_hash = compute_data_hash(db)
    if meta.data_hash != current_hash:
        return {"status": "outdated", "message": "Прогноз устарел, данные были изменены"}
    
    # Загружаем прогноз
    forecasts = load_forecast_from_db(db)
    if not forecasts:
        return {"status": "not_found", "message": "Прогноз не найден"}
    
    return {
        "status": "ok",
        "created_at": meta.created_at.isoformat() if meta.created_at else None,
        "periods": meta.periods,
        "forecasts": forecasts
    }
