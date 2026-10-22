"""Config flow for the Diftar integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import CookieJar
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import DiftarAuthError, DiftarClient, DiftarConnectionError
from .const import CONF_MUNICIPALITY, CONF_STREET, DOMAIN, LOGGER
from .iok import IokAddressError, IokCalendarClient, IokError

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)
PASSWORD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


class DiftarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Diftar."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DiftarOptionsFlow:
        """Return the options flow."""
        return DiftarOptionsFlow()

    async def _async_validate(
        self, username: str, password: str
    ) -> tuple[str | None, dict[str, str]]:
        """Try to log in. Return the customer number and any form errors."""
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=CookieJar()
        )
        try:
            customer_number = await DiftarClient(
                session, username, password
            ).async_get_account_id()
        except DiftarAuthError:
            return None, {"base": "invalid_auth"}
        except DiftarConnectionError:
            return None, {"base": "cannot_connect"}
        except Exception:
            LOGGER.exception("Unexpected error while logging in")
            return None, {"base": "unknown"}
        finally:
            await session.close()
        return customer_number, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the mijndiftar.be username and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            customer_number, errors = await self._async_validate(
                username, user_input[CONF_PASSWORD]
            )
            if customer_number:
                await self.async_set_unique_id(customer_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Diftar {customer_number}",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauth flow when the stored password stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            customer_number, errors = await self._async_validate(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if customer_number:
                await self.async_set_unique_id(customer_number)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PASSWORD_SCHEMA,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the username or password of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            customer_number, errors = await self._async_validate(
                username, user_input[CONF_PASSWORD]
            )
            if customer_number:
                await self.async_set_unique_id(customer_number)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, {CONF_USERNAME: entry.data[CONF_USERNAME]}
            ),
            errors=errors,
        )


class DiftarOptionsFlow(OptionsFlow):
    """Change the address used for the iok.be collection calendar."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the municipality and street."""
        errors: dict[str, str] = {}
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=CookieJar()
        )
        client = IokCalendarClient(session)
        try:
            if user_input is not None:
                street = user_input[CONF_STREET].strip()
                try:
                    await client.async_get_pickups(
                        user_input[CONF_MUNICIPALITY], street
                    )
                except IokAddressError:
                    errors[CONF_STREET] = "address_not_found"
                except IokError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        data={
                            CONF_MUNICIPALITY: user_input[CONF_MUNICIPALITY],
                            CONF_STREET: street,
                        }
                    )
            try:
                municipalities = await client.async_get_municipalities()
            except IokError:
                municipalities = []
        finally:
            await session.close()

        calendar = getattr(self.config_entry, "runtime_data", None)
        current = calendar.calendar.address if calendar and calendar.calendar else None
        suggested = user_input or (
            {CONF_MUNICIPALITY: current[0], CONF_STREET: current[1]} if current else {}
        )
        municipality = (
            SelectSelector(
                SelectSelectorConfig(
                    options=municipalities, mode=SelectSelectorMode.DROPDOWN
                )
            )
            if municipalities
            else TextSelector()
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_MUNICIPALITY): municipality,
                vol.Required(CONF_STREET): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )
