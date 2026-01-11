export const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export const PROCESS_NAMES = {
  admission: 'Приём',
  transfers_in: 'Переводы',
  expelled: 'Отчисления',
  academic_leave: 'Академ',
  restored: 'Восстановление'
};

export const PROCESS_KEYS = Object.keys(PROCESS_NAMES);
