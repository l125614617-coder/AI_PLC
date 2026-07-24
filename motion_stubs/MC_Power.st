FUNCTION_BLOCK MC_Power
VAR_INPUT
    Enable : BOOL;
END_VAR
VAR_OUTPUT
    Status : BOOL;
    Error  : BOOL;
END_VAR
VAR_IN_OUT
    Axis : AXIS_REF;
END_VAR

IF Axis.EStopActive THEN
    Axis.Enabled := FALSE;
    Axis.Busy := FALSE;
    Axis.Error := TRUE;
    Axis.ErrorID := 1;
    Axis.AxisState := 6;
ELSIF Enable AND Axis.AxisState <> 6 THEN
    Axis.Enabled := TRUE;
ELSE
    Axis.Enabled := FALSE;
END_IF;

IF Axis.AxisState = 0 AND Axis.Enabled THEN
    Axis.AxisState := 1;
END_IF;
IF NOT Axis.Enabled AND Axis.AxisState <> 6 THEN
    Axis.AxisState := 0;
END_IF;

Status := Axis.Enabled;
Error := Axis.Error;

END_FUNCTION_BLOCK
