"""Config flow to configure the Nuki integration."""
import logging

from pynuki import NukiBridge
from pynuki.bridge import InvalidCredentialsException
from requests.exceptions import RequestException
import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.components import dhcp
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResult

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT, DOMAIN
from .helpers import parse_id

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        vol.Required(CONF_TOKEN): str,
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})


async def validate_input(hass, data):
    """Validate the user input allows us to connect.

    Data has the keys from USER_SCHEMA with values provided by the user.
    """

    try:
        bridge = await hass.async_add_executor_job(
            NukiBridge,
            data[CONF_HOST],
            data[CONF_TOKEN],
            data[CONF_PORT],
            True,
            DEFAULT_TIMEOUT,
        )

        info = await hass.async_add_executor_job(bridge.info)
    except InvalidCredentialsException as err:
        raise InvalidAuth from err
    except RequestException as err:
        raise CannotConnect from err

    return info


class NukiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Nuki config flow."""

    def __init__(self):
        """Initialize the Nuki config flow."""
        self.discovery_schema = {}
        self._data = {}

    async def async_step_import(self, user_input=None):
        """Handle a flow initiated by import."""
        return await self.async_step_validate(user_input)

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        return await self.async_step_validate(user_input)

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> FlowResult:
        """Prepare configuration for a DHCP discovered Nuki bridge."""
        await self.async_set_unique_id(discovery_info.hostname[12:].upper())

        self._abort_if_unique_id_configured()

        self.discovery_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=discovery_info.ip): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_TOKEN): str,
            }
        )

        return await self.async_step_validate()

    async def async_step_reauth(self, data):
        """Perform reauth upon an API authentication error."""
        self._data = data

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Dialog that inform the user that reauth is required."""
        errors = {}
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=REAUTH_SCHEMA
            )

        conf = {
            CONF_HOST: self._data[CONF_HOST],
            CONF_PORT: self._data[CONF_PORT],
            CONF_TOKEN: user_input[CONF_TOKEN],
        }

        try:
            info = await validate_input(self.hass, conf)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        if not errors:
            existing_entry = await self.async_set_unique_id(
                parse_id(info["ids"]["hardwareId"])
            )
            if existing_entry:
                self.hass.config_entries.async_update_entry(existing_entry, data=conf)
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(existing_entry.entry_id)
                )
                return self.async_abort(reason="reauth_successful")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=REAUTH_SCHEMA, errors=errors
        )

    async def async_step_validate(self, user_input=None):
        """Handle init step of a flow."""

        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            if "base" not in errors:
                bridge_id = parse_id(info["ids"]["hardwareId"])
                await self.async_set_unique_id(bridge_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=bridge_id, data=user_input)

        data_schema = self.discovery_schema or USER_SCHEMA
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
