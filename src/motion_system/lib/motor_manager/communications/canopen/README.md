# canopen

SocketCAN CANopen transport for `motor_manager`.

This module provides:

- `canopen::CanopenMaster`, derived from `motor_interface::MotorMaster`
- `canopen::CanopenController`, derived from `motor_interface::MotorController`

The implementation uses Linux raw CAN sockets, NMT start, expedited SDO read/write, RPDO1/RPDO2 transmit, and TPDO1/TPDO2 receive.

## Device setup

Bring up a SocketCAN interface before starting `MotorManager`. For example, with a CANable adapter:

```bash
sudo slcand -o -c -s8 -S 3000000 /dev/CANable can0
sudo ip link set can0 txqueuelen 1000
sudo ip link set can0 up
```

The code binds to `can<can_interface_index>`. With `can_interface_index: 0`, the interface name is `can0`.

## YAML fields

CANopen masters are selected with `masters[].type: canopen`.

```yaml
masters:
  - id: 0
    type: canopen
    number_of_slaves: 1
    can_interface_index: 0
    can_bitrate: 1000000
    slaves:
      - controller_index: 0
        driver_id: 0
        can_id: 1
        profile_mode: 0
```

| Field | Meaning |
| --- | --- |
| `can_interface_index` | SocketCAN suffix. `0` means `can0`. |
| `can_bitrate` | Stored in the master config; the current code expects the interface to already be configured. |
| `can_id` | CANopen device ID. Valid IDs are `1` through `MAX_CONTROLLER_SIZE - 1`. |
| `profile_mode` | `0`: position, `1`: velocity, `2`: effort. Used when setting operation mode and filtering target PDOs. |

## COB-IDs

| Constant | Value | Purpose |
| --- | --- | --- |
| `COB_NMT` | `0x000` | NMT commands. |
| `COB_TPDO1_BASE` | `0x180` | TPDO1 base plus node ID. |
| `COB_TPDO2_BASE` | `0x280` | TPDO2 base plus node ID. |
| `COB_RPDO1_BASE` | `0x200` | RPDO1 base plus node ID. |
| `COB_RPDO2_BASE` | `0x300` | RPDO2 base plus node ID. |
| `COB_SDO_TX` | `0x580` | SDO response base plus node ID. |
| `COB_SDO_RX` | `0x600` | SDO request base plus node ID. |
| `COB_HEARTBEAT` | `0x700` | Heartbeat base plus node ID. |

## `CanopenMaster`

| Function | Description |
| --- | --- |
| `initialize()` | Creates a non-blocking raw CAN socket and binds to `can<interface_index>`. |
| `activate()` | Sends NMT start to all nodes. |
| `deactivate()` | Closes the CAN socket. |
| `transmit()` | Sends dirty RPDO buffers as RPDO1 and, when needed, RPDO2. |
| `receive()` | Processes all available TPDO and heartbeat frames. |
| `registerNodes(node_id)` | Registers a node ID and validates its range. |
| `node(node_id)` | Returns the node buffer used by a controller. |
| `writeSdo(...)` | Sends expedited 1/2/4-byte SDO writes and waits up to one second for the response. |
| `readSdo(...)` | Sends an SDO read request and copies returned data. |

`apply_application_time()` and `save_clock()` are no-ops for CANopen.

## `CanopenController`

| Function | Description |
| --- | --- |
| `initialize(master, driver)` | Casts the master, registers the node, gets its node buffer, and configures SDO/PDO entries. |
| `registerEntries()` | Runs SDO setup and PDO setup. |
| `enable()` | Reads statusword from TPDO data and writes the driver enable controlword into RPDO data. |
| `disable()` | Writes the disable transition controlword into RPDO data. |
| `check(status)` | Handles set-point acknowledge and clears the new-set-point bit when needed. |
| `write(command)` | Converts command fields to raw RPDO bytes and marks the node dirty for transmit. |
| `read(status)` | Copies TPDO bytes, applies driver scaling, and fills `motor_frame_t`. |

The controller supports target IDs `ID_CONTROLWORD`, `ID_TARGET_POSITION`, `ID_TARGET_VELOCITY`, and `ID_TARGET_EFFORT` on writes, and status/error/current position/current velocity/current effort IDs on reads.

## PDO mapping behavior

`addSlaveConfigPdos()` writes standard CANopen mapping objects:

- RPDO mapping: `0x1600`, `0x1601`
- TPDO mapping: `0x1A00`, `0x1A01`
- RPDO communication: `0x1400`, `0x1401`
- TPDO communication: `0x1800`, `0x1801`

Entries are packed into PDO1 until 8 bytes, then PDO2. If a PDO2 segment would exceed 8 bytes, initialization throws.
