import importlib
import pkgutil
import sys
from typing import List, Type
from src.scrapers.base import BaseScraper

# A registry of active scraper classes
_SCRAPER_REGISTRY: List[Type[BaseScraper]] = []

def register_scraper(cls: Type[BaseScraper]):
    """Decorator or helper to register a scraper class."""
    if cls not in _SCRAPER_REGISTRY:
        _SCRAPER_REGISTRY.append(cls)
    return cls

def get_scrapers() -> List[Type[BaseScraper]]:
    """
    Dynamically discovers and returns all registered scraper classes
    inheriting from BaseScraper.
    """
    # Load all submodules in the current package to trigger registration
    package_name = __name__
    package = sys.modules[package_name]
    
    for _, module_name, _ in pkgutil.walk_packages(package.__path__, package_name + "."):
        try:
            importlib.import_module(module_name)
        except Exception as e:
            print(f"Warning: Failed to import scraper module {module_name}: {e}")
            
    # Collect all subclasses of BaseScraper that are not abstract (having scrape defined)
    discovered = []
    # If using decorator registration
    for scraper_cls in _SCRAPER_REGISTRY:
        if scraper_cls not in discovered:
            discovered.append(scraper_cls)
            
    # Fallback to dynamic subclass check if decorators aren't used
    for subclass in BaseScraper.__subclasses__():
        if subclass not in discovered and not getattr(subclass, "__abstractmethods__", None):
            discovered.append(subclass)
            
    return discovered
