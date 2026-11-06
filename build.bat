@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo   Сборка CleanSpace.exe
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
  echo [Ошибка] Python не найден. Установите Python 3.10-3.13 с python.org
  echo и отметьте галочку "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist .venv (
  echo Создаю виртуальное окружение...
  python -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat

echo Устанавливаю зависимости...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-dev.txt || goto :fail

echo Запускаю тесты (только временные папки)...
python -m pytest -q || goto :fail

echo Собираю EXE...
pyinstaller --noconfirm --clean CleanSpace.spec || goto :fail

echo Готовлю портативную версию...
if exist dist\CleanSpace_portable rmdir /s /q dist\CleanSpace_portable
mkdir dist\CleanSpace_portable
copy /y dist\CleanSpace.exe dist\CleanSpace_portable\ >nul
echo Этот файл включает портативный режим: настройки и история хранятся рядом с программой.> dist\CleanSpace_portable\portable.txt
powershell -NoProfile -Command "Compress-Archive -Path 'dist\CleanSpace_portable\*' -DestinationPath 'dist\CleanSpace_portable.zip' -Force"

echo.
echo Готово!
echo   dist\CleanSpace.exe          - программа (один файл, Python не нужен)
echo   dist\CleanSpace_portable.zip - портативная версия
echo.
pause
exit /b 0

:fail
echo.
echo [Ошибка] Сборка не удалась. Пролистайте вывод выше, чтобы увидеть причину.
pause
exit /b 1
