@echo off
:: Cambiar a la unidad y ruta exacta de tu proyecto
cd /d C:\Users\hgonzalh\Pictures\programa control de clientes\proyecto web 5.2

:: Si usas un entorno virtual, descomenta la siguiente línea y pon su ruta:
:: call venv\Scripts\activate.bat

:: Ejecutar Streamlit en modo silencioso/headless
streamlit run app_streamlit.py --server.headless true

pause