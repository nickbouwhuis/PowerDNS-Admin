import os
import typing
from pathlib import Path

_instance = None
basedir = os.path.abspath(Path(os.path.dirname(__file__)).parent)


class SettingException(Exception):
    pass


class Setting(object):
    default: typing.Any
    description: str | None
    environment: bool
    label: str | None
    loaded: bool
    name: str | None
    prompts: dict | None
    stype: type | None
    value: typing.Any

    def __init__(self, name, stype, default=None, label=None, description=None, prompts=None, value=None):
        self.name = name
        self.stype = stype
        self.default = default
        self.label = label
        self.description = description
        self.prompts = prompts
        self.value = value
        self.environment = False
        self.loaded = False

    def __repr__(self):
        return f'<Setting {self._name}({self._stype})={self._value}>'

    def __str__(self):
        return str(self._value)

    def __bool__(self):
        if self.stype == bool:
            return self._value
        elif self.stype in (int, float):
            return type(self._value) in (int, float) and self._value > 0
        elif self.stype == dict:
            return isinstance(self._value, dict) and len(self._value.keys()) > 0
        elif self.stype == list:
            return isinstance(self._value, list) and len(self._value) > 0
        return str(self._value).lower() in ('true', 't', 'yes', 'y', '1')

    def __int__(self):
        return int(self._value)

    def __float__(self):
        return float(self._value)

    def __complex__(self):
        return complex(self._value)

    def __bytes__(self):
        return bytes(self._value)

    def __hash__(self):
        return hash(self._value)

    def __len__(self):
        if self.stype in (dict, list):
            return len(self._value)
        raise TypeError(f'The setting type {self.stype} has no len()')

    def save(self):
        import json
        import traceback
        from flask import current_app
        from powerdnsadmin.models.setting import Setting as SettingModel
        from powerdnsadmin.models.base import db

        # Only attempt to store the value to the database if it hasn't been set from the environment
        if not self.environment:
            model = SettingModel.query.filter_by(name=self.name).first()
            if model is None:
                current_app.logger.debug(
                    'Setting {0} does not exist in database. Adding new record to db session.'.format(self.name))
                model = SettingModel(name=self.name, value=None)
                db.session.add(model)

            value = self.value
            if isinstance(self.value, dict) or isinstance(self.value, list):
                value = json.dumps(self.value)

            current_app.logger.debug('Saving setting {0} to the database with value: '.format(self.name, value))

            try:
                model.value = value
                db.session.commit()
                current_app.logger.debug('Setting {0} saved to the database.'.format(self.name))
                return True
            except Exception as e:
                current_app.logger.error(
                    'Failed to save setting {0} to the database. DETAIL: {1}'.format(self.name, e))
                current_app.logger.debug(traceback.format_exec())
                db.session.rollback()

            return False


class Settings(object):
    _cache = None
    _instance = None
    """ The Settings instance cache. """

    def __init__(self):
        """ Initializes the Settings instance cache. """
        self._cache = {}

    def all(self, flatten=False):
        """ Returns the Settings instance cache. """
        if flatten:
            return {k: v.value for k, v in self._cache.items()}
        return self._cache

    def get(self, name, cache=True, default=None):
        """ Returns a Setting object from the Settings instance cache. """
        from powerdnsadmin.models.setting import Setting as SettingModel

        # Return the default value if the given setting isn't registered in the cache.
        if not self.has(name):
            return default

        # Attempt to extract the current value of the setting from the database, and update the cache if found.
        if not cache:
            db = SettingModel.query.filter_by(name=name).first()
            if db is not None:
                self._cache.get(name).value = self.convert_type(name, db.value)

        # Return the Setting object from the cache.
        return self._cache.get(name, default)

    def has(self, name):
        """ Returns True if the Setting object exists in the Settings instance cache. """
        return name in self._cache

    def set(self, name, value):
        """ Adds a Setting object to the Settings instance cache. """
        self._cache[name] = value

    def value(self, name, default=None):
        """ Returns the value of the Setting object from the Settings instance cache, or the default argument
        value otherwise. """
        if not self.has(name):
            return default
        return self.get(name, default).value

    def convert_type(self, name, value):
        import json
        from json import JSONDecodeError

        if not self.has(name):
            raise ValueError('Setting does not exist: {}'.format(name))

        setting = self.get(name)

        # Handle boolean values
        if setting.stype == bool and isinstance(value, str):
            if value.lower() in ['True', 'true', '1'] or value is True:
                return True
            else:
                return False

        # Handle float values
        if setting.stype == float:
            return float(value)

        # Handle integer values
        if setting.stype == int:
            return int(value)

        if (setting.stype == dict or setting.stype == list) and isinstance(value, str) and len(value) > 0:
            try:
                return json.loads(value)
            except JSONDecodeError as e:
                # Provide backwards compatibility for legacy non-JSON format
                value = value.replace("'", '"').replace('True', 'true').replace('False', 'false')
                try:
                    return json.loads(value)
                except JSONDecodeError as e:
                    raise ValueError('Cannot parse json {} for variable {}'.format(value, name))

        if setting.stype == str:
            return str(value)

        return value

    def load_environment(self, app, config=None):
        """ Load app settings from environment variables when defined. """
        import os
        from powerdnsadmin.models.setting import Setting as SettingModel

        # Load Docker specific configuration instead of the default configuration
        if os.path.exists(os.path.join(app.root_path, 'docker_config.py')):
            app.config.from_object('powerdnsadmin.docker_config')

        # Load default configuration
        else:
            app.config.from_object('powerdnsadmin.default_config')

        # Load config file from path defined in FLASK_CONF env variable
        if 'FLASK_CONF' in os.environ:
            app.config.from_envvar('FLASK_CONF')

        # Load configuration injected into the app initialization
        if config is not None:
            if isinstance(config, dict):
                app.config.update(config)
            elif config.endswith('.py'):
                app.config.from_pyfile(config)

        # Load configuration from environment variables
        for var_name, setting in self.all().items():
            env_name = var_name.upper()
            current_value = None

            if env_name in app.config:
                current_value = app.config[env_name]

            if env_name + '_FILE' in os.environ:
                if env_name in os.environ:
                    raise AttributeError(
                        "Both {} and {} are set but are exclusive.".format(
                            env_name, env_name + '_FILE'))
                with open(os.environ[env_name + '_FILE']) as f:
                    current_value = f.read()
                f.close()

            elif env_name in os.environ:
                current_value = os.environ[env_name]

            if current_value is not None:
                current_value = self.convert_type(var_name, current_value)
                setting = self.get(var_name)
                setting.value = current_value
                setting.environment = True
                setting.loaded = True
                app.config[env_name] = current_value

    def load_database(self):
        """ Load app settings from database when not already loaded elsewhere. """
        from powerdnsadmin.models.setting import Setting as SettingModel

        settings = Settings.instance()
        model = SettingModel()

        # Load settings from the database that haven't already been loaded from the environment
        for record in model.query.all():
            if settings.has(record.name) and not (setting := settings.get(record.name)).loaded:
                setting.value = self.convert_type(record.name, record.value)
                setting.loaded = True

    @staticmethod
    def instance():
        if Settings._instance is None:
            Settings._instance = Settings()
        return Settings._instance