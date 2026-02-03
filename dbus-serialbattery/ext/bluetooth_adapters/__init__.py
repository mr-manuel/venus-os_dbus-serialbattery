__version__ = "2.1.1"


from platform import system

from .adapters import BluetoothAdapters
from .const import (
    DEFAULT_ADDRESS,
    DEFAULT_CONNECTION_SLOTS,
    MACOS_DEFAULT_BLUETOOTH_ADAPTER,
    UNIX_DEFAULT_BLUETOOTH_ADAPTER,
    WINDOWS_DEFAULT_BLUETOOTH_ADAPTER,
)

if system() != "Windows":
    from .dbus import (
        BlueZDBusObjects,
        get_bluetooth_adapter_details,
        get_bluetooth_adapters,
        get_dbus_managed_objects,
    )

from .history import AdvertisementHistory, load_history_from_managed_objects
from .mac_lookup import get_manufacturer_from_mac
from .models import (
    ADAPTER_ADDRESS,
    ADAPTER_CONNECTION_SLOTS,
    ADAPTER_HW_VERSION,
    ADAPTER_MANUFACTURER,
    ADAPTER_PASSIVE_SCAN,
    ADAPTER_PRODUCT,
    ADAPTER_PRODUCT_ID,
    ADAPTER_SW_VERSION,
    ADAPTER_TYPE,
    ADAPTER_VENDOR_ID,
    AdapterDetails,
)
from .storage import (
    DiscoveredDeviceAdvertisementData,
    DiscoveredDeviceAdvertisementDataDict,
    DiscoveryStorageType,
    discovered_device_advertisement_data_from_dict,
    discovered_device_advertisement_data_to_dict,
    expire_stale_scanner_discovered_device_advertisement_data,
)
from .systems import get_adapters
from .systems.linux_hci import get_adapters_from_hci
from .util import adapter_human_name, adapter_model, adapter_unique_name

__all__ = [
    "ADAPTER_ADDRESS",
    "ADAPTER_CONNECTION_SLOTS",
    "ADAPTER_HW_VERSION",
    "ADAPTER_MANUFACTURER",
    "ADAPTER_PASSIVE_SCAN",
    "ADAPTER_PRODUCT",
    "ADAPTER_PRODUCT_ID",
    "ADAPTER_SW_VERSION",
    "ADAPTER_TYPE",
    "ADAPTER_VENDOR_ID",
    "DEFAULT_ADDRESS",
    "DEFAULT_CONNECTION_SLOTS",
    "MACOS_DEFAULT_BLUETOOTH_ADAPTER",
    "UNIX_DEFAULT_BLUETOOTH_ADAPTER",
    "WINDOWS_DEFAULT_BLUETOOTH_ADAPTER",
    "AdapterDetails",
    "AdvertisementHistory",
    "BlueZDBusObjects",
    "BluetoothAdapters",
    "DiscoveredDeviceAdvertisementData",
    "DiscoveredDeviceAdvertisementDataDict",
    "DiscoveryStorageType",
    "adapter_human_name",
    "adapter_model",
    "adapter_unique_name",
    "discovered_device_advertisement_data_from_dict",
    "discovered_device_advertisement_data_to_dict",
    "expire_stale_scanner_discovered_device_advertisement_data",
    "get_adapters",
    "get_adapters_from_hci",
    "get_bluetooth_adapter_details",
    "get_bluetooth_adapters",
    "get_dbus_managed_objects",
    "get_manufacturer_from_mac",
    "load_history_from_managed_objects",
]
