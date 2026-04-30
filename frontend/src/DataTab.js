import React from 'react';
import { groupDataByYear } from './utils';

function DataTab({
  data,
  loading,
  message,
  file,
  fileName,
  handleFileChange,
  handleUpload,
  uploading,
  handleDeleteAll,
  scriptFileName,
  handleScriptFileChange,
  handleScriptUpload,
  scriptUploading,
  scripts,
  handleScriptDelete,
  handleScriptRun,
  scriptRunning
}) {
  const groupedData = groupDataByYear(data);
  const years = Object.keys(groupedData).sort((a, b) => parseInt(b) - parseInt(a));

  return (
    <div>
      <div className="card mb-4 shadow-sm">
        <div className="card-body">
          <h2 className="card-title mb-4">Загрузка данных</h2>
          <div className="d-flex flex-wrap gap-3 align-items-center">
            <div>
              <input
                id="file-input"
                type="file"
                accept=".csv"
                onChange={handleFileChange}
                className="d-none"
              />
              <label htmlFor="file-input" className="btn btn-primary">
                Выбрать файл
              </label>
            </div>
            {fileName && (
              <span className="text-success fw-bold">Выбран: {fileName}</span>
            )}
            <button
              className="btn btn-success"
              onClick={handleUpload}
              disabled={!file || uploading}
            >
              {uploading ? 'Загрузка...' : 'Загрузить'}
            </button>
          </div>
          <hr className="my-4" />
          <h5 className="mb-3">Скрипты загрузки источников (Python)</h5>
          <div className="d-flex flex-wrap gap-3 align-items-center mb-3">
            <div>
              <input
                id="script-file-input"
                type="file"
                accept=".py"
                onChange={handleScriptFileChange}
                className="d-none"
              />
              <label htmlFor="script-file-input" className="btn btn-outline-primary">
                Выбрать скрипт
              </label>
            </div>
            {scriptFileName && (
              <span className="text-success fw-bold">Выбран: {scriptFileName}</span>
            )}
            <button
              className="btn btn-outline-success"
              onClick={handleScriptUpload}
              disabled={!scriptFileName || scriptUploading}
            >
              {scriptUploading ? 'Загрузка...' : 'Загрузить скрипт'}
            </button>
          </div>
          <div className="small text-muted mb-3">
            Контракт скрипта: функция <code>main()</code>, возвращающая список записей
            или объект <code>{'{ data: [...] }'}</code> с полями:
            <code> year, course, admission, transfers_in, expelled, academic_leave, restored</code>.
          </div>
          {scripts.length === 0 ? (
            <div className="text-muted">Скрипты не загружены.</div>
          ) : (
            <div className="table-responsive">
              <table className="table table-sm table-bordered align-middle mb-0">
                <thead>
                  <tr>
                    <th>Скрипт</th>
                    <th>Размер (байт)</th>
                    <th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {scripts.map((script) => (
                    <tr key={script.name}>
                      <td>{script.name}</td>
                      <td>{script.size}</td>
                      <td className="d-flex gap-2">
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => handleScriptRun(script.name)}
                          disabled={scriptRunning === script.name}
                        >
                          {scriptRunning === script.name ? 'Выполнение...' : 'Запустить'}
                        </button>
                        <button
                          className="btn btn-sm btn-outline-danger"
                          onClick={() => handleScriptDelete(script.name)}
                        >
                          Удалить
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {message.text && (
            <div className={`alert alert-${message.type === 'error' ? 'danger' : 'success'} mt-3 mb-0`}>
              {message.text}
            </div>
          )}
        </div>
      </div>

      <div className="card shadow-sm">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center mb-4">
            <h2 className="card-title mb-0">Загруженные данные</h2>
            {data.length > 0 && (
              <button className="btn btn-danger" onClick={handleDeleteAll}>
                Удалить все данные
              </button>
            )}
          </div>

          {loading ? (
            <div className="text-center py-5 text-primary">Загрузка данных...</div>
          ) : data.length === 0 ? (
            <div className="text-center py-5 text-muted">
              Нет загруженных данных. Загрузите CSV файл для начала работы.
            </div>
          ) : (
            <div className="table-responsive">
              {years.map(year => (
                <div key={year} className="year-group">
                  <div className="year-header">Год: {year}</div>
                  <table className="table table-hover year-table mb-0">
                    <thead>
                      <tr>
                        <th>Курс</th>
                        <th>Приём</th>
                        <th>Переводы (входящие)</th>
                        <th>Отчисления</th>
                        <th>Академ</th>
                        <th>Восстановление</th>
                      </tr>
                    </thead>
                    <tbody>
                      {groupedData[year]
                        .sort((a, b) => a.course - b.course)
                        .map(item => (
                          <tr key={item.id}>
                            <td>{item.course}</td>
                            <td>{item.admission}</td>
                            <td>{item.transfers_in}</td>
                            <td>{item.expelled}</td>
                            <td>{item.academic_leave}</td>
                            <td>{item.restored}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DataTab;
