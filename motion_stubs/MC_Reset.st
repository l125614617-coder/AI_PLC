FUNCTION_BLOCK MC_Reset
VAR_INPUT
    Execute : BOOL;
END_VAR
VAR_OUTPUT
    Done  : BOOL;
    Error : BOOL;
END_VAR
VAR_IN_OUT
    Axis : AXIS_REF;
END_VAR
VAR
    prevExecute : BOOL;
END_VAR

IF Execute AND NOT prevExecute THEN
    IF NOT Axis.EStopActive THEN
        Axis.Error := FALSE;
        Axis.ErrorID := 0;
        Axis.CommandAborted := FALSE;
        IF Axis.AxisState = 6 THEN
            Axis.AxisState := 1;
        END_IF;
        Done := TRUE;
    ELSE
        Done := FALSE;
    END_IF;
ELSE
    Done := FALSE;
END_IF;
prevExecute := Execute;
Error := Axis.Error;

END_FUNCTION_BLOCK
