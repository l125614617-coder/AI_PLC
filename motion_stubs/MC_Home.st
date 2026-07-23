FUNCTION_BLOCK MC_Home
VAR_INPUT
    Execute  : BOOL;
    Velocity : REAL;
END_VAR
VAR_OUTPUT
    Done  : BOOL;
    Busy  : BOOL;
    Error : BOOL;
END_VAR
VAR_IN_OUT
    Axis : AXIS_REF;
END_VAR
VAR
    execRise : R_TRIG;
    active   : BOOL;
END_VAR

execRise(CLK := Execute);

IF execRise.Q AND NOT active THEN
    IF NOT Axis.Enabled OR Axis.EStopActive THEN
        Error := TRUE;
    ELSE
        active := TRUE;
        Axis.Busy := TRUE;
        Axis.Done := FALSE;
        Axis.Homed := FALSE;
        Axis.AxisState := 2;
        Error := FALSE;
    END_IF;
END_IF;

IF active THEN
    IF Axis.EStopActive THEN
        Axis.Velocity := 0.0;
        Axis.Busy := FALSE;
        Axis.Error := TRUE;
        Axis.ErrorID := 1;
        Axis.AxisState := 6;
        active := FALSE;
        Error := TRUE;
    ELSIF Axis.HomeSwitch OR Axis.LimitNeg THEN
        Axis.Velocity := 0.0;
        Axis.Position := 0.0;
        Axis.Homed := TRUE;
        Axis.Done := TRUE;
        Axis.Busy := FALSE;
        Axis.AxisState := 1;
        active := FALSE;
    ELSE
        Axis.Velocity := Velocity;
        Axis.Position := Axis.Position - Velocity * 0.01;
    END_IF;
END_IF;

Busy := active;
Done := Axis.Homed AND NOT active;

END_FUNCTION_BLOCK
