FUNCTION_BLOCK MC_Stop
VAR_INPUT
    Execute      : BOOL;
    Deceleration : REAL;
END_VAR
VAR_OUTPUT
    Done : BOOL;
    Busy : BOOL;
END_VAR
VAR_IN_OUT
    Axis : AXIS_REF;
END_VAR
VAR
    active : BOOL;
END_VAR

IF Execute THEN
    active := TRUE;
END_IF;

IF active THEN
    Axis.AxisState := 5;
    Axis.Busy := TRUE;
    IF Axis.Velocity > 0.0 THEN
        Axis.Velocity := Axis.Velocity - Deceleration * 0.01;
        IF Axis.Velocity <= 0.0 THEN
            Axis.Velocity := 0.0;
        END_IF;
    ELSIF Axis.Velocity < 0.0 THEN
        Axis.Velocity := Axis.Velocity + Deceleration * 0.01;
        IF Axis.Velocity >= 0.0 THEN
            Axis.Velocity := 0.0;
        END_IF;
    END_IF;

    IF Axis.Velocity = 0.0 THEN
        Done := TRUE;
        Axis.Busy := FALSE;
        Axis.Active := FALSE;
        Busy := FALSE;
        IF NOT Execute THEN
            active := FALSE;
            IF Axis.AxisState = 5 THEN
                Axis.AxisState := 1;
            END_IF;
        END_IF;
    ELSE
        Done := FALSE;
        Busy := TRUE;
    END_IF;
ELSE
    Done := FALSE;
    Busy := FALSE;
END_IF;

END_FUNCTION_BLOCK
