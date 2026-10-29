@echo off
REM Gera dist\BuscaVagas.exe e dist\CandidatarVagas.exe
REM (rode no Windows com Python 3.12 instalado).
REM Python 3.13+ pode falhar por causa do numpy fixado pelo JobSpy.

py -3.12 -m pip install -r requirements-build.txt
if errorlevel 1 goto erro

echo.
echo === Gerando BuscaVagas.exe ===
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name BuscaVagas ^
  --collect-all jobspy --collect-all tls_client app.py
if errorlevel 1 goto erro

echo.
echo === Gerando CandidatarVagas.exe ===
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name CandidatarVagas ^
  --collect-all playwright --collect-all google.genai --collect-all pypdf --collect-all docx ^
  candidatar_app.py
if errorlevel 1 goto erro

echo.
echo Copiando arquivos de apoio para dist\...
xcopy /E /I /Y perfis dist\perfis >nul
copy /Y COMO_USAR.txt dist\ >nul

echo.
echo Pronto! Os programas estao em dist\BuscaVagas.exe e dist\CandidatarVagas.exe
echo Copie a pasta "dist" inteira (com a subpasta perfis) para distribuir.
pause
exit /b 0
:erro
echo.
echo Algo deu errado. Confira se o Python 3.12 esta instalado (comando: py -3.12 --version)
pause
exit /b 1
