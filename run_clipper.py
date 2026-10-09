"""Titik masuk untuk PyInstaller / `python run_clipper.py`."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from clipper.gui import main
    main()
