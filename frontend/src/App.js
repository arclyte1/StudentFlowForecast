import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';
import DataTab from './DataTab';
import ForecastTab from './ForecastTab';
import { API_URL } from './constants';

function App() {
  const [activeTab, setActiveTab] = useState('data');
  const [file, setFile] = useState(null);
  const [fileName, setFileName] = useState('');
  const [message, setMessage] = useState({ type: '', text: '' });
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [scriptFile, setScriptFile] = useState(null);
  const [scriptFileName, setScriptFileName] = useState('');
  const [scripts, setScripts] = useState([]);
  const [scriptUploading, setScriptUploading] = useState(false);
  const [scriptRunning, setScriptRunning] = useState('');

  useEffect(() => {
    loadData();
    loadScripts();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_URL}/api/data`);
      setData(response.data);
      setMessage({ type: '', text: '' });
    } catch (error) {
      setMessage({ 
        type: 'error', 
        text: 'Ошибка при загрузке данных: ' + (error.response?.data?.detail || error.message) 
      });
    } finally {
      setLoading(false);
    }
  };

  const loadScripts = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/source-scripts`);
      setScripts(response.data.scripts || []);
    } catch (error) {
      setMessage({
        type: 'error',
        text: 'Ошибка при загрузке списка скриптов: ' + (error.response?.data?.detail || error.message)
      });
    }
  };

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      if (selectedFile.name.endsWith('.csv')) {
        setFile(selectedFile);
        setFileName(selectedFile.name);
        setMessage({ type: '', text: '' });
      } else {
        setMessage({ type: 'error', text: 'Пожалуйста, выберите CSV файл' });
        setFile(null);
        setFileName('');
      }
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setMessage({ type: 'error', text: 'Пожалуйста, выберите файл' });
      return;
    }

    setUploading(true);
    setMessage({ type: '', text: '' });

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post(`${API_URL}/api/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      setMessage({ 
        type: 'success', 
        text: `Данные успешно загружены! Добавлено записей: ${response.data.records_added}` 
      });
      setFile(null);
      setFileName('');
      document.getElementById('file-input').value = '';
      await loadData();
    } catch (error) {
      setMessage({ 
        type: 'error', 
        text: 'Ошибка при загрузке файла: ' + (error.response?.data?.detail || error.message) 
      });
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteAll = async () => {
    if (!window.confirm('Вы уверены, что хотите удалить все данные?')) {
      return;
    }

    try {
      await axios.delete(`${API_URL}/api/data`);
      setMessage({ type: 'success', text: 'Все данные удалены' });
      await loadData();
    } catch (error) {
      setMessage({ 
        type: 'error', 
        text: 'Ошибка при удалении данных: ' + (error.response?.data?.detail || error.message) 
      });
    }
  };

  const handleScriptFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (!selectedFile) return;
    if (!selectedFile.name.endsWith('.py')) {
      setMessage({ type: 'error', text: 'Пожалуйста, выберите Python скрипт (.py)' });
      setScriptFile(null);
      setScriptFileName('');
      return;
    }
    setScriptFile(selectedFile);
    setScriptFileName(selectedFile.name);
    setMessage({ type: '', text: '' });
  };

  const handleScriptUpload = async () => {
    if (!scriptFile) {
      setMessage({ type: 'error', text: 'Выберите скрипт для загрузки' });
      return;
    }
    setScriptUploading(true);
    const formData = new FormData();
    formData.append('file', scriptFile);
    try {
      const response = await axios.post(`${API_URL}/api/source-scripts`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setMessage({ type: 'success', text: `Скрипт загружен: ${response.data.name}` });
      setScriptFile(null);
      setScriptFileName('');
      const input = document.getElementById('script-file-input');
      if (input) input.value = '';
      await loadScripts();
    } catch (error) {
      setMessage({
        type: 'error',
        text: 'Ошибка загрузки скрипта: ' + (error.response?.data?.detail || error.message)
      });
    } finally {
      setScriptUploading(false);
    }
  };

  const handleScriptDelete = async (name) => {
    if (!window.confirm(`Удалить скрипт ${name}?`)) return;
    try {
      await axios.delete(`${API_URL}/api/source-scripts/${encodeURIComponent(name)}`);
      setMessage({ type: 'success', text: `Скрипт удален: ${name}` });
      await loadScripts();
    } catch (error) {
      setMessage({
        type: 'error',
        text: 'Ошибка удаления скрипта: ' + (error.response?.data?.detail || error.message)
      });
    }
  };

  const handleScriptRun = async (name) => {
    setScriptRunning(name);
    try {
      const response = await axios.post(`${API_URL}/api/source-scripts/${encodeURIComponent(name)}/run`);
      setMessage({
        type: 'success',
        text: `Скрипт ${name} выполнен. Загружено записей: ${response.data.records_added}`
      });
      await loadData();
    } catch (error) {
      setMessage({
        type: 'error',
        text: 'Ошибка выполнения скрипта: ' + (error.response?.data?.detail || error.message)
      });
    } finally {
      setScriptRunning('');
    }
  };

  return (
    <div className="container mt-4">
      <div className="bg-dark text-white p-4 mb-4 rounded shadow">
        <h1 className="mb-0">Прогноз контингента студентов</h1>
      </div>

      {/* Вкладки */}
      <ul className="nav nav-tabs mb-4">
        <li className="nav-item">
          <button
            className={`nav-link ${activeTab === 'data' ? 'active' : ''}`}
            onClick={() => setActiveTab('data')}
          >
            Импорт/просмотр данных
          </button>
        </li>
        <li className="nav-item">
          <button
            className={`nav-link ${activeTab === 'forecast' ? 'active' : ''}`}
            onClick={() => setActiveTab('forecast')}
          >
            Построение прогнозов
          </button>
        </li>
      </ul>

      {/* Содержимое вкладок */}
      <div className="tab-content">
        {activeTab === 'data' && (
          <DataTab
            data={data}
            loading={loading}
            message={message}
            setFile={setFile}
            setFileName={setFileName}
            file={file}
            fileName={fileName}
            handleFileChange={handleFileChange}
            handleUpload={handleUpload}
            uploading={uploading}
            handleDeleteAll={handleDeleteAll}
            loadData={loadData}
            scriptFileName={scriptFileName}
            handleScriptFileChange={handleScriptFileChange}
            handleScriptUpload={handleScriptUpload}
            scriptUploading={scriptUploading}
            scripts={scripts}
            handleScriptDelete={handleScriptDelete}
            handleScriptRun={handleScriptRun}
            scriptRunning={scriptRunning}
          />
        )}
        {activeTab === 'forecast' && (
          <ForecastTab data={data} />
        )}
      </div>
    </div>
  );
}

export default App;
