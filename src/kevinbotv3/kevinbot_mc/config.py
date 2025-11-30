from enum import StrEnum


class MotorConfigurationKey(StrEnum):
    # Safety
    ALLOW_ENABLED = "allowEn"
    BRAKE_AT_ESTOP = "brakeEst"
    DRIVE_MAX_VOLTAGE = "drvMaxV"

    # Motor config
    SENSOR_TYPE = "sensTyp"
    POLE_PAIRS = "polePair"
    KV = "kv"
    PHASE_RESISTANCE = "phRes"
    PHASE_INDUCTANCE = "phInd"
    PPR = "ppr"
    PWM_FREQ = "pwmFreq"

    # Runtime limits
    VOLTAGE_LIMIT = "vLim"
    CURRENT_LIMIT = "iLim"
    VELOCITY_LIMIT = "velLim"

    # FOC
    FOC_MODULATION = "focMod"
    MODULATION_CENTERED = "modCtr"

    # Torque
    TORQUE_CONTROL = "trqCtrl"

    # Sensor
    SENSOR_OFFSET = "sensOff"
    SENSOR_ALIGN_VOLTAGE = "sensAlV"
    VELOCITY_INDEX_SEARCH = "velIdx"
    ZERO_ELECTRIC_ANGLE = "zeroAng"
    SENSOR_DIRECTION = "sensDir"

    # Velocity PID
    VELOCITY_PID_P = "vPidP"
    VELOCITY_PID_I = "vPidI"
    VELOCITY_PID_D = "vPidD"
    VELOCITY_PID_RAMP = "vPidRmp"
    VELOCITY_PID_LIMIT = "vPidLim"
    VELOCITY_LPF_TF = "vLpfTf"

    # Angle P
    ANGLE_P = "angP"
    ANGLE_LPF_TF = "angLpfTf"

    # Current Q PID
    CURRENT_Q_PID_P = "qPidP"
    CURRENT_Q_PID_I = "qPidI"
    CURRENT_Q_PID_D = "qPidD"
    CURRENT_Q_PID_RAMP = "qPidRmp"
    CURRENT_Q_PID_LIMIT = "qPidLim"
    CURRENT_Q_LPF_TF = "qLpfTf"

    # Current D PID
    CURRENT_D_PID_P = "dPidP"
    CURRENT_D_PID_I = "dPidI"
    CURRENT_D_PID_D = "dPidD"
    CURRENT_D_PID_RAMP = "dPidRmp"
    CURRENT_D_PID_LIMIT = "dPidLim"
    CURRENT_D_LPF_TF = "dLpfTf"

    # Brake/Float
    BRAKE_AT_NEUTRAL = "brakeNtr"

    # Control
    TONE_AMPLITUDE = "toneAmp"

    # Status LED
    STATUS_LED_BRIGHTNESS = "ledBr"

    # Watchdog
    UART_WATCHDOG_ENABLED = "uartWdEn"
    UART_WATCHDOG_TIMEOUT_MS = "uartWdTm"

    # Comms
    COMM_SOURCE = "commSrc"
    UART_BAUD_RATE = "uartBr"

    # Identifiers
    DEVICE_USER_NAME = "devUsrNm"