from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import pandas as pd
import io
from prophet import Prophet

from database import SessionLocal, engine, Base
from models import StudentData, ForecastData, ForecastMeta
from schemas import StudentDataResponse, StudentDataCreate
import logging
import hashlib

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
        # Читаем содержимое файла
        contents = await file.read()
        df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        
        # Проверяем наличие необходимых колонок
        required_columns = ['year', 'course', 'admission', 'transfers_in', 'expelled', 'academic_leave', 'restored']
        if not all(col in df.columns for col in required_columns):
            raise HTTPException(
                status_code=400, 
                detail=f"CSV файл должен содержать колонки: {', '.join(required_columns)}"
            )
        
        db = next(get_db())
        
        # Удаляем старые данные для тех же годов и курсов
        for _, row in df.iterrows():
            db.query(StudentData).filter(
                StudentData.year == int(row['year']),
                StudentData.course == int(row['course'])
            ).delete()
        
        # Добавляем новые данные
        records_added = 0
        for _, row in df.iterrows():
            student_data = StudentData(
                year=int(row['year']),
                course=int(row['course']),
                admission=int(row['admission']),
                transfers_in=int(row['transfers_in']),
                expelled=int(row['expelled']),
                academic_leave=int(row['academic_leave']),
                restored=int(row['restored'])
            )
            db.add(student_data)
            records_added += 1
        
        db.commit()
        
        return {
            "message": "Данные успешно загружены",
            "records_added": records_added
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при обработке файла: {str(e)}")


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
    Строит прогноз на основе загруженных данных с использованием Prophet
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
    
    df["ds"] = pd.to_datetime(df["year"].astype(str) + "-01-01")
    
    # Определяем диапазон годов в данных
    min_year = df["year"].min()
    max_year = df["year"].max()
    unique_years = sorted(df["year"].unique())
    logging.info(f"Диапазон годов в данных: {min_year} - {max_year}, всего {len(unique_years)} лет")
    
    # Логируем статистику по процессам
    for process_key in ['admission', 'transfers_in', 'expelled', 'academic_leave', 'restored']:
        non_zero_count = (df[process_key] != 0).sum()
        total_count = len(df)
        logging.info(f"Процесс {process_key}: {non_zero_count}/{total_count} ненулевых значений")
    
    forecasts = {}
    successful_forecasts = 0
    skipped_forecasts = 0
    
    for course in [1, 2, 3, 4]:
        forecasts[course] = {}
        course_df = df[df["course"] == course]
        
        if len(course_df) == 0:
            logging.info(f"Курс {course}: нет данных")
            continue
        
        logging.info(f"Курс {course}: найдено {len(course_df)} записей за {course_df['year'].nunique()} лет")
        
        for process_key, process_name in PROCESS_NAMES.items():
            # Создаем DataFrame для Prophet
            prophet_df = course_df[["ds", process_key]].copy()
            prophet_df = prophet_df.rename(columns={process_key: "y"})
            
            # Удаляем строки с NaN
            prophet_df = prophet_df.dropna()
            
            # Проверяем количество точек
            if len(prophet_df) < 2:
                logging.info(f"Курс {course}, процесс {process_key}: недостаточно данных ({len(prophet_df)} точек, нужно минимум 2)")
                skipped_forecasts += 1
                continue
            
            # Убеждаемся, что y имеет числовой тип
            prophet_df["y"] = pd.to_numeric(prophet_df["y"], errors='coerce')
            prophet_df = prophet_df.dropna()
            
            if len(prophet_df) < 2:
                logging.info(f"Курс {course}, процесс {process_key}: недостаточно валидных числовых данных ({len(prophet_df)} точек)")
                skipped_forecasts += 1
                continue
            
            # Проверяем наличие вариаций
            # Пропускаем только если все значения одинаковые И равны нулю
            unique_values = prophet_df["y"].nunique()
            if unique_values < 2:
                first_value = float(prophet_df["y"].iloc[0])
                if first_value == 0:
                    logging.info(f"Курс {course}, процесс {process_key}: все значения нулевые ({len(prophet_df)} точек), пропускаем")
                    skipped_forecasts += 1
                    continue
                else:
                    # Если все значения одинаковые, но не нули, все равно строим прогноз
                    logging.info(f"Курс {course}, процесс {process_key}: все значения одинаковые ({first_value}), но не нули, строим прогноз")
            
            logging.info(f"Курс {course}, процесс {process_key}: {len(prophet_df)} точек данных, уникальных значений: {unique_values}, диапазон: {prophet_df['y'].min()}-{prophet_df['y'].max()}")
            
            try:
                # Проверяем данные перед построением модели
                logging.info(f"Данные для курс {course}, процесс {process_key}: min={prophet_df['y'].min()}, max={prophet_df['y'].max()}, mean={prophet_df['y'].mean():.2f}")
                
                # Проверяем, что данные валидны
                if prophet_df.empty:
                    logging.warning(f"Курс {course}, процесс {process_key}: DataFrame пуст после обработки")
                    skipped_forecasts += 1
                    continue
                
                # Проверяем наличие колонок ds и y
                if 'ds' not in prophet_df.columns or 'y' not in prophet_df.columns:
                    logging.warning(f"Курс {course}, процесс {process_key}: отсутствуют необходимые колонки")
                    skipped_forecasts += 1
                    continue
                
                # Настраиваем Prophet для работы с годовыми данными
                # Отключаем автоматическое определение сезонности для малых наборов данных
                model = Prophet(
                    yearly_seasonality=True if len(prophet_df) >= 3 else False,
                    weekly_seasonality=False,
                    daily_seasonality=False,
                    seasonality_mode='additive'
                )
                
                logging.info(f"Начинаем обучение модели для курс {course}, процесс {process_key}...")
                model.fit(prophet_df)
                logging.info(f"Модель обучена успешно для курс {course}, процесс {process_key}")
                
                future = model.make_future_dataframe(periods=periods, freq="Y")
                fc = model.predict(future)
                
                # Форматируем результат
                forecast_data = []
                for _, row in fc.iterrows():
                    # Округляем и гарантируем неотрицательные значения
                    yhat = max(0, round(row["yhat"], 2))
                    yhat_lower = max(0, round(row["yhat_lower"], 2))
                    yhat_upper = max(0, round(row["yhat_upper"], 2))
                    
                    forecast_data.append({
                        "ds": row["ds"].strftime("%Y-%m-%d"),
                        "year": row["ds"].year,
                        "yhat": yhat,
                        "yhat_lower": yhat_lower,
                        "yhat_upper": yhat_upper
                    })
                
                forecasts[course][process_key] = {
                    "name": process_name,
                    "data": forecast_data
                }
                successful_forecasts += 1
                logging.info(f"✓ Успешно построен прогноз для курс {course}, процесс {process_key} ({len(forecast_data)} точек)")
            except Exception as e:
                # Логируем ошибку для отладки
                error_msg = str(e)
                logging.error(f"✗ Ошибка при построении прогноза для курс {course}, процесс {process_key}: {error_msg}")
                import traceback
                logging.error(traceback.format_exc())
                skipped_forecasts += 1
                continue
    
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
    logging.info(f"Итого: успешно построено {successful_forecasts} прогнозов, пропущено {skipped_forecasts} комбинаций")
    logging.info(f"Успешно построено прогнозов для {total_forecasts} комбинаций курс/процесс")
    
    # Сохраняем прогноз в базу данных
    save_forecast_to_db(db, forecasts, data_hash, periods)
    
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
