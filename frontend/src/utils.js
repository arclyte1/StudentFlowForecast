// Утилиты для работы с данными

/**
 * Получает значение процесса для курса и года из forecasts или исторических данных
 */
export const getProcessValue = (forecasts, historicalData, course, processKey, year, maxHistoricalYear) => {
  // Для исторических годов используем реальные данные
  if (year <= maxHistoricalYear && historicalData && historicalData.length > 0) {
    const historicalItem = historicalData.find(d => d.course === course && d.year === year);
    if (historicalItem && historicalItem[processKey] !== undefined) {
      return historicalItem[processKey] || 0;
    }
  }
  
  // Для прогнозных годов используем прогнозы
  if (!forecasts[course] || !forecasts[course][processKey] || !forecasts[course][processKey].data) {
    return 0;
  }
  const item = forecasts[course][processKey].data.find(d => d && d.year === year);
  return item && item.yhat !== undefined ? Math.max(0, item.yhat) : 0;
};

/**
 * Собирает все годы из forecasts
 */
export const getAllYearsFromForecasts = (forecasts) => {
  const allYears = new Set();
  Object.values(forecasts).forEach(courseData => {
    if (courseData && typeof courseData === 'object') {
      Object.values(courseData).forEach(processData => {
        if (processData && processData.data && Array.isArray(processData.data)) {
          processData.data.forEach(item => {
            if (item && item.year) {
              allYears.add(item.year);
            }
          });
        }
      });
    }
  });
  return Array.from(allYears).sort((a, b) => a - b);
};

/**
 * Группирует данные по годам
 */
export const groupDataByYear = (data) => {
  const grouped = {};
  data.forEach(item => {
    if (!grouped[item.year]) {
      grouped[item.year] = [];
    }
    grouped[item.year].push(item);
  });
  return grouped;
};
