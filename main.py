import sys


def check_environment():
    print("Доступ к проекту и запуск Python работают!")
    print(f"Версия Python: {sys.version.split()[0]}")
    print(f"Интерпретатор: {sys.executable}")


if __name__ == "__main__":
    check_environment()
