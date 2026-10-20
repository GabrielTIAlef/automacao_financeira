"""Rotina compartilhada; confirma solicitação, não conclusão do refresh."""
from contextlib import contextmanager
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.config import AutomationError as ETLError, configured_path, required as required_env
from src.notifications import notify

LOG = logging.getLogger(__name__)


@contextmanager
def profile_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".gestao_refresh.lock"
    try:
        marker.mkdir()
    except FileExistsError:
        raise ETLError("Perfil Chrome reservado por outra execução; não remova locks de processo ativo.") from None
    try:
        if any(directory.glob("Singleton*")):
            raise ETLError("Perfil Chrome ocupado; nenhum lock do navegador foi removido.")
        yield
    finally:
        marker.rmdir()


def run(*, allow_live=False, driver_factory=None, wait_factory=None, action_factory=None,
        directory=None, profile=None, dataset=None):
    if not allow_live:
        raise ETLError('Refresh externo desativado; autorize explicitamente a execução.')
    # Imports tardios: importar os entrypoints não abre Chrome nem exige credenciais.
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.common.action_chains import ActionChains

    dataset = dataset if dataset is not None else required_env("POWERBI_DATASET_NAME")
    directory = directory if directory is not None else configured_path("CHROME_USER_DATA_DIR")
    profile = profile if profile is not None else required_env("CHROME_PROFILE_DIR")
    driver_factory = driver_factory or (lambda options: webdriver.Chrome(service=Service(), options=options))
    wait_factory = wait_factory or WebDriverWait
    action_factory = action_factory or ActionChains
    options = webdriver.ChromeOptions()
    for option in (f"--user-data-dir={directory}", f"--profile-directory={profile}",
                   "--no-first-run", "--no-default-browser-check", "--headless=new",
                   "--disable-gpu", "--window-size=1920,1080"):
        options.add_argument(option)
    import os
    binary = os.getenv("CHROME_BINARY", "").strip()
    if binary:
        options.binary_location = binary
    driver = None
    with profile_lock(directory):
        try:
            driver = driver_factory(options)
            driver.get("https://app.powerbi.com/groups/me/list?experience=power-bi")
            wait_factory(driver, 40).until(
                EC.presence_of_element_located((By.XPATH, "//a[@data-testid='item-name']")))
            for block in driver.find_elements(By.XPATH, "//span[contains(@class, 'col-name')]"):
                # Qualquer erro inesperado interrompe; não esconder falha da interface.
                name = (block.find_element(By.XPATH, ".//a[@data-testid='item-name']")
                        .get_attribute("aria-label") or "").strip()
                if name == dataset:
                    action_factory(driver).move_to_element(block).perform()
                    button = wait_factory(block, 10).until(EC.element_to_be_clickable(
                        (By.XPATH, ".//button[@data-testid='quick-action-button-Atualizar agora']")))
                    button.click()
                    LOG.info("Solicitação de atualização Power BI enviada; conclusão não verificada.")
                    return {"status": "requested", "completion_verified": False}
            raise ETLError("Dataset não encontrado ou atualização indisponível.")
        except Exception:
            notify("refresh_failed", allow_live=allow_live)
            raise ETLError("Solicitação Power BI falhou; conclusão não confirmada.") from None
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    LOG.warning("Não foi possível encerrar o driver Chrome.")


if __name__ == "__main__":
    from src.cli import main
    sys.exit(main(["refresh", *sys.argv[1:]]))
