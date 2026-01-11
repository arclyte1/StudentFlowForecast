import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Area,
  AreaChart,
  ComposedChart,
  Bar,
  ReferenceArea
} from 'recharts';
import { API_URL, PROCESS_NAMES, PROCESS_KEYS } from './constants';
import { getProcessValue, getAllYearsFromForecasts } from './utils';

function ForecastTab({ data }) {
  const [forecasts, setForecasts] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeProcess, setActiveProcess] = useState('admission');
  const [selectedCourse, setSelectedCourse] = useState(null);
  const [forecastStatus, setForecastStatus] = useState('loading'); // 'loading', 'not_found', 'outdated', 'ok'
  const [forecastCreatedAt, setForecastCreatedAt] = useState(null);

  // Загружаем сохраненный прогноз при монтировании и при изменении данных
  useEffect(() => {
    if (data && data.length > 0) {
      loadSavedForecast();
    }
  }, [data]);

  const loadSavedForecast = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/forecast/saved`);
      console.log('Статус сохраненного прогноза:', response.data);
      
      if (response.data.status === 'ok') {
        setForecasts(response.data.forecasts);
        setForecastStatus('ok');
        setForecastCreatedAt(response.data.created_at);
        setError('');
      } else if (response.data.status === 'outdated') {
        setForecastStatus('outdated');
        setForecasts(null);
      } else {
        setForecastStatus('not_found');
        setForecasts(null);
      }
    } catch (err) {
      console.error('Ошибка при загрузке сохраненного прогноза:', err);
      setForecastStatus('not_found');
    }
  };

  const loadForecasts = async (force = false) => {
    setLoading(true);
    setError('');
    try {
      console.log('Построение прогноза...', { dataLength: data.length, force });
      const response = await axios.get(`${API_URL}/api/forecast?periods=5&force=${force}`);
      console.log('Прогноз построен:', response.data);
      
      setForecasts(response.data);
      setForecastStatus('ok');
      setForecastCreatedAt(new Date().toISOString());
      
      if (!response.data || Object.keys(response.data).length === 0) {
        setError('Не удалось построить прогноз. Убедитесь, что есть данные хотя бы за 2 года для процессов с ненулевыми значениями.');
      }
    } catch (err) {
      console.error('Ошибка при построении прогноза:', err);
      const errorMsg = err.response?.data?.detail || err.message || 'Неизвестная ошибка';
      setError('Ошибка при построении прогноза: ' + errorMsg);
      setForecasts(null);
    } finally {
      setLoading(false);
    }
  };

  // Вычисляем минимальный и максимальный годы из исторических данных один раз
  const maxHistoricalYear = data && data.length > 0 
    ? Math.max(...data.map(d => d.year)) 
    : 0;
  const minHistoricalYear = data && data.length > 0 
    ? Math.min(...data.map(d => d.year)) 
    : null;

  // Объединяем исторические данные и прогнозы
  const getCombinedData = (course, processKey) => {
    if (!forecasts?.[course]?.[processKey]) {
      return [];
    }

    const forecastData = forecasts[course][processKey].data;
    const historicalMap = {};
    data.filter(d => d.course === course).forEach(d => {
      historicalMap[d.year] = d[processKey];
    });

    return forecastData.map(item => ({
      year: item.year,
      date: item.ds,
      actual: item.year <= maxHistoricalYear ? historicalMap[item.year] || null : null,
      forecast: item.yhat,
      lower: item.yhat_lower,
      upper: item.yhat_upper,
      isHistorical: item.year <= maxHistoricalYear
    }));
  };

  // Расчет численности студентов по формуле, где S(Y,C) - численность студентов на курсе C в году Y
  // S(Y,1) = admission(Y,1) + transfers_in(Y,1) - expelled(Y,1) - academic_leave(Y,1) + restored(Y,1)
  // S(Y,C) = S(Y-1,C-1) + transfers_in(Y,C) - expelled(Y,C) - academic_leave(Y,C) + restored(Y,C)
  const getStudentCountData = () => {
    if (!forecasts) return [];

    const sortedYears = getAllYearsFromForecasts(forecasts);
    
    const getValue = (course, processKey, year) => {
      return getProcessValue(forecasts, data, course, processKey, year, maxHistoricalYear);
    };

    // Хранилище для S(Y, C) - численность студентов
    const studentCount = {}; // { year: { course: count } }

    // Вычисляем численность для всех годов в прямом порядке
    sortedYears.forEach(year => {
      studentCount[year] = {};
      
      for (let course = 1; course <= 4; course++) {
        const admission = getValue(course, 'admission', year);
        const transfers_in = getValue(course, 'transfers_in', year);
        const expelled = getValue(course, 'expelled', year);
        const academic_leave = getValue(course, 'academic_leave', year);
        const restored = getValue(course, 'restored', year);

        if (course === 1) {
          studentCount[year][course] = Math.max(0, admission + transfers_in - expelled - academic_leave + restored);
        } else {
          const prevCount = studentCount[year - 1]?.[course - 1] || 0;
          studentCount[year][course] = Math.max(0, prevCount + transfers_in - expelled - academic_leave + restored);
        }
      }
    });

    // Для исторических годов пересчитываем курсы 2-4, где нет данных за предыдущий год
    // Используем обратную формулу из данных следующего года для вычисления начальной численности
    if (minHistoricalYear !== null && maxHistoricalYear > minHistoricalYear) {
      for (let year = minHistoricalYear; year <= maxHistoricalYear; year++) {
        const nextYear = year + 1;
        
        for (let course = 2; course <= 4; course++) {
          const prevYear = year - 1;
          const prevCourse = course - 1;
          
          let needsReverseCalculation = false;
          
          let checkYear = year;
          let checkCourse = course;
          while (checkCourse > 1) {
            const checkPrevYear = checkYear - 1;
            if (checkPrevYear < minHistoricalYear) {
              needsReverseCalculation = true;
              break;
            }
            checkYear = checkPrevYear;
            checkCourse = checkCourse - 1;
          }
          
          if (needsReverseCalculation) {
            const getProcessValues = (c, y) => ({
              transfers: getValue(c, 'transfers_in', y),
              expelled: getValue(c, 'expelled', y),
              academic: getValue(c, 'academic_leave', y),
              restored: getValue(c, 'restored', y)
            });

            // Сначала проверяем, можно ли использовать численность предыдущего курса в том же году
            if (studentCount[year]?.[prevCourse] > 0) {
              const prevCourseCount = studentCount[year][prevCourse];
              const yearValues = getProcessValues(course, year);
              studentCount[year][course] = Math.max(0, 
                prevCourseCount + yearValues.transfers - yearValues.expelled - yearValues.academic + yearValues.restored
              );
            } 
            // Если нет, используем обратную формулу из следующего года
            else if (nextYear <= maxHistoricalYear && studentCount[nextYear]?.[course] !== undefined) {
              const nextYearCount = studentCount[nextYear][course];
              const nextValues = getProcessValues(course, nextYear);
              const prevCourseCount = nextYearCount - nextValues.transfers + nextValues.expelled + nextValues.academic - nextValues.restored;
              
              const yearValues = getProcessValues(course, year);
              studentCount[year][course] = Math.max(0,
                prevCourseCount + yearValues.transfers - yearValues.expelled - yearValues.academic + yearValues.restored
              );
            }
          }
        }
      }
    }

    // Формируем данные для таблицы и графика
    const tableData = sortedYears.map(year => {
      const row = { year, isForecast: year > maxHistoricalYear };
      let total = 0;
      
      for (let course = 1; course <= 4; course++) {
        const count = Math.round(studentCount[year][course] || 0);
        row[`course${course}`] = count;
        total += count;
      }
      
      row.total = total;
      return row;
    });

    return tableData;
  };

  const studentCountData = getStudentCountData();

  // Получаем данные для таблицы приток/отток
  const getFlowTableData = () => {
    if (!forecasts) return [];

    const sortedYears = getAllYearsFromForecasts(forecasts);
    const tableData = [];

    sortedYears.forEach(year => {
      const row = { year };
      
      // Суммируем по всем курсам для всех процессов
      const sums = {};
      PROCESS_KEYS.forEach(key => sums[key] = 0);

      for (let course = 1; course <= 4; course++) {
        PROCESS_KEYS.forEach(key => {
          const value = getProcessValue(forecasts, data, course, key, year, maxHistoricalYear);
          sums[key] += value;
        });
      }

      row.admission = Math.round(Math.max(0, sums.admission));
      row.transfers = Math.round(Math.max(0, sums.transfers_in));
      row.expelled = Math.round(Math.max(0, sums.expelled));
      row.academic = Math.round(Math.max(0, sums.academic_leave));
      row.restored = Math.round(Math.max(0, sums.restored));
      
      tableData.push(row);
    });

    return tableData;
  };

  if (!data || data.length === 0) {
    return (
      <div className="card shadow-sm">
        <div className="card-body">
          <div className="text-center py-5 text-muted">
            Нет данных для построения прогноза. Загрузите данные на вкладке "Импорт/просмотр данных".
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card shadow-sm">
      <div className="card-body">
      {/* Заголовок и кнопка для построения/обновления прогноза */}
      <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
        <div>
          <h2 className="mb-0">Построение прогнозов</h2>
          {forecastStatus === 'ok' && forecastCreatedAt && (
            <small className="text-muted d-block">
              Прогноз от: {new Date(forecastCreatedAt).toLocaleString('ru-RU')}
            </small>
          )}
        </div>
        {/* Показываем кнопку только если прогноз устарел или не найден */}
        {(forecastStatus === 'outdated' || forecastStatus === 'not_found' || !forecasts) && (
          <button 
            onClick={() => loadForecasts(true)} 
            disabled={loading}
            className={`btn ${loading ? 'btn-secondary' : forecastStatus === 'outdated' ? 'btn-warning' : 'btn-success'}`}
          >
            {loading ? 'Построение...' : (forecastStatus === 'outdated' ? 'Обновить прогноз (данные изменились)' : 'Построить прогноз')}
          </button>
        )}
      </div>

      {forecastStatus === 'outdated' && !loading && (
        <div className="alert alert-warning mb-4">
          ⚠️ Данные были изменены. Рекомендуется обновить прогноз.
        </div>
      )}

      {loading && (
        <div className="text-center py-5 text-primary">Построение прогноза... Пожалуйста, подождите. Это может занять некоторое время.</div>
      )}

      {error && (
        <div className="alert alert-danger">
          <strong>Ошибка:</strong> {error}
          <button 
            onClick={() => loadForecasts(true)} 
            className="btn btn-primary mt-2"
          >
            Попробовать снова
          </button>
        </div>
      )}

      {!loading && !error && !forecasts && forecastStatus !== 'outdated' && (
        <div className="text-center py-5 text-muted">
          <p>Прогноз еще не построен. Нажмите кнопку выше, чтобы начать построение прогноза.</p>
          <button 
            onClick={() => loadForecasts(true)} 
            className="btn btn-primary mt-3"
          >
            Построить прогноз
          </button>
        </div>
      )}

      {!loading && !error && forecasts && Object.keys(forecasts).length === 0 && (
        <div className="text-center py-5 text-muted">
          <p>Не удалось построить прогноз. Возможно, недостаточно данных.</p>
          <p className="small mt-2">
            Требуется минимум 2 года данных для построения прогноза.
          </p>
          <button 
            onClick={loadForecasts} 
            className="btn btn-primary mt-3"
          >
            Попробовать снова
          </button>
        </div>
      )}

      {!loading && !error && forecasts && Object.keys(forecasts).length > 0 && (
        <>
          {/* ГЛАВНАЯ ТАБЛИЦА: Прогноз численности студентов */}
          <div className="mb-4">
            <h3 className="mb-3">📊 Прогноз численности студентов</h3>
            
            {/* График численности студентов */}
            {studentCountData.length > 0 && (() => {
              // Находим первый прогнозный год
              const firstForecastYear = studentCountData.find(d => d.year > maxHistoricalYear)?.year;
              
              return (
                <div className="mb-4 bg-light p-4 rounded">
                  <ResponsiveContainer width="100%" height={350}>
                    <ComposedChart data={studentCountData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="year" tick={{ fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 12 }} />
                      {firstForecastYear && (
                        <ReferenceArea 
                          x1={firstForecastYear} 
                          x2={studentCountData[studentCountData.length - 1].year}
                          fill="#fff3cd" 
                          fillOpacity={0.5}
                          stroke="#ffc107"
                          strokeWidth={2}
                          strokeDasharray="5 5"
                        />
                      )}
                      <Tooltip 
                        formatter={(value, name) => {
                          const labels = {
                            course1: 'Курс 1',
                            course2: 'Курс 2',
                            course3: 'Курс 3',
                            course4: 'Курс 4',
                            total: 'Всего'
                          };
                          return [Math.round(value), labels[name] || name];
                        }}
                      />
                      <Legend 
                        formatter={(value) => {
                          const labels = {
                            course1: 'Курс 1',
                            course2: 'Курс 2',
                            course3: 'Курс 3',
                            course4: 'Курс 4',
                            total: 'Всего'
                          };
                          return labels[value] || value;
                        }}
                      />
                      <Bar dataKey="course1" stackId="a" fill="#3498db" name="course1" />
                      <Bar dataKey="course2" stackId="a" fill="#2ecc71" name="course2" />
                      <Bar dataKey="course3" stackId="a" fill="#f39c12" name="course3" />
                      <Bar dataKey="course4" stackId="a" fill="#9b59b6" name="course4" />
                      <Line type="monotone" dataKey="total" stroke="#e74c3c" strokeWidth={3} dot={{ r: 5 }} name="total" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              );
            })()}

            {/* Таблица численности студентов */}
            <div className="bg-light p-4 rounded">
              <div className="table-responsive">
                <table className="table table-hover">
                  <thead className="table-dark">
                    <tr>
                      <th>Год</th>
                      <th>Курс 1</th>
                      <th>Курс 2</th>
                      <th>Курс 3</th>
                      <th>Курс 4</th>
                      <th className="bg-secondary">Всего</th>
                    </tr>
                  </thead>
                  <tbody>
                    {studentCountData.map(row => {
                      const isForecast = row.year > maxHistoricalYear;
                      return (
                        <tr key={row.year} className={isForecast ? 'table-warning fst-italic' : ''}>
                          <td><strong>{row.year}{isForecast ? ' (прогноз)' : ''}</strong></td>
                          <td>{row.course1}</td>
                          <td>{row.course2}</td>
                          <td>{row.course3}</td>
                          <td>{row.course4}</td>
                          <td className={`fw-bold ${isForecast ? 'bg-warning bg-opacity-50' : 'bg-light'}`}>{row.total}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

      {/* Вкладки процессов */}
      <div className="process-tabs">
        {Object.entries(PROCESS_NAMES).map(([key, name]) => (
          <button
            key={key}
            className={`process-tab ${activeProcess === key ? 'active' : ''}`}
            onClick={() => setActiveProcess(key)}
          >
            {name}
          </button>
        ))}
      </div>

      {/* Графики по курсам */}
      <div className="course-selector">
        <label>Выберите курс для детального просмотра:</label>
        <select value={selectedCourse || ''} onChange={(e) => setSelectedCourse(e.target.value ? parseInt(e.target.value) : null)}>
          <option value="">Все курсы</option>
          <option value="1">Курс 1</option>
          <option value="2">Курс 2</option>
          <option value="3">Курс 3</option>
          <option value="4">Курс 4</option>
        </select>
      </div>

      {/* График прогноза */}
      <div className="forecast-chart mb-4">
        <h3 className="mb-3">Прогноз: {PROCESS_NAMES[activeProcess]}</h3>
        {selectedCourse ? (
          forecasts[selectedCourse] && forecasts[selectedCourse][activeProcess] ? (
            <ForecastChart
              data={getCombinedData(selectedCourse, activeProcess)}
              processName={PROCESS_NAMES[activeProcess]}
              course={selectedCourse}
            />
          ) : (
            <div className="text-muted">Нет данных для курса {selectedCourse}</div>
          )
        ) : (
          <div className="all-courses-charts">
            {[1, 2, 3, 4].map(course => (
              forecasts[course] && forecasts[course][activeProcess] ? (
                <div key={course} className="course-chart-wrapper">
                  <h4 className="mb-3">Курс {course}</h4>
                  <ForecastChart
                    data={getCombinedData(course, activeProcess)}
                    processName={PROCESS_NAMES[activeProcess]}
                    course={course}
                  />
                </div>
              ) : null
            ))}
          </div>
        )}
      </div>

      {/* Таблицы */}
      <div className="row mt-4">
        <div className="col-12">
          <div className="card bg-light">
            <div className="card-body">
              <h3 className="card-title mb-3">Приток / Отток</h3>
              {getFlowTableData().length > 0 ? (
                <div className="table-responsive">
                  <table className="table table-hover">
                    <thead className="table-dark">
                      <tr>
                        <th>Год</th>
                        <th>Приём</th>
                        <th>Переводы</th>
                        <th>Отчисления</th>
                        <th>Академ</th>
                        <th>Восстановления</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getFlowTableData().map(row => {
                        const isForecast = row.year > maxHistoricalYear;
                        return (
                          <tr key={row.year} className={isForecast ? 'table-warning fst-italic' : ''}>
                            <td>{row.year}{isForecast ? ' (прогноз)' : ''}</td>
                            <td>{row.admission}</td>
                            <td>{row.transfers}</td>
                            <td>{row.expelled}</td>
                            <td>{row.academic}</td>
                            <td>{row.restored}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-muted p-4 mb-0">Нет данных для отображения</p>
              )}
            </div>
          </div>
        </div>
      </div>
        </> 
      )}
      </div>
    </div>
  );
}

function ForecastChart({ data, processName, course }) {
  if (!data || data.length === 0) {
    return <div>Нет данных для отображения</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis 
          dataKey="year" 
          tick={{ fontSize: 12 }}
        />
        <YAxis tick={{ fontSize: 12 }} />
        <Tooltip 
          formatter={(value, name) => {
            if (name === 'actual') return [Math.round(value), 'Факт'];
            if (name === 'forecast') return [Math.round(value), 'Прогноз'];
            if (name === 'lower') return [Math.round(value), 'Нижняя граница'];
            if (name === 'upper') return [Math.round(value), 'Верхняя граница'];
            return value;
          }}
        />
        <Legend />
        <Area
          type="monotone"
          dataKey="actual"
          stroke="#8884d8"
          fill="#8884d8"
          fillOpacity={0.6}
          name="Факт"
          strokeWidth={2}
        />
        <Area
          type="monotone"
          dataKey="upper"
          stroke="#ffc107"
          fill="#fff3cd"
          fillOpacity={0.3}
          name="Верхняя граница"
          strokeWidth={1}
          strokeDasharray="5 5"
        />
        <Area
          type="monotone"
          dataKey="lower"
          stroke="#ffc107"
          fill="#fff3cd"
          fillOpacity={0.3}
          name="Нижняя граница"
          strokeWidth={1}
          strokeDasharray="5 5"
        />
        <Line
          type="monotone"
          dataKey="forecast"
          stroke="#ff7300"
          strokeWidth={2}
          strokeDasharray="5 5"
          name="Прогноз"
          dot={{ r: 4 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export default ForecastTab;

