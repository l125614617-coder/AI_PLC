FUNCTION_BLOCK MC_MoveVelocity
VAR_INPUT
    Execute      : BOOL;
    Velocity     : REAL;
    Acceleration : REAL;
END_VAR
VAR_OUTPUT
    InVelocity     : BOOL;
    Busy           : BOOL;
    Active         : BOOL;
    CommandAborted : BOOL;
    Error          : BOOL;
END_VAR
VAR_IN_OUT
    Axis : AXIS_REF;
END_VAR
VAR
    myCommand : DINT;
    owned     : BOOL;
END_VAR

IF Execute THEN
    IF NOT owned THEN
        IF NOT Axis.Enabled OR Axis.EStopActive OR Axis.AxisState = 6 THEN
            CommandAborted := TRUE;
            Error := TRUE;
        ELSIF Axis.Busy AND Axis.CommandId <> myCommand THEN
            CommandAborted := TRUE;
            Error := TRUE;
        ELSIF (Velocity > 0.0 AND Axis.LimitPos) OR
              (Velocity < 0.0 AND Axis.LimitNeg) THEN
            Axis.Velocity := 0.0;
            Axis.Active := FALSE;
            Axis.InVelocity := FALSE;
            Axis.Error := TRUE;
            Axis.ErrorID := 2;
            Axis.AxisState := 6;
            Axis.CommandAborted := TRUE;
            CommandAborted := TRUE;
            owned := FALSE;
        ELSE
            Axis.CommandId := Axis.CommandId + 1;
            myCommand := Axis.CommandId;
            owned := TRUE;
            Axis.TargetVelocity := Velocity;
            Axis.Active := TRUE;
            Axis.AxisState := 4;
            CommandAborted := FALSE;
            Error := FALSE;
        END_IF;
    END_IF;

    IF owned AND Axis.CommandId = myCommand THEN
        IF Axis.EStopActive THEN
            Axis.Velocity := 0.0;
            Axis.Active := FALSE;
            Axis.InVelocity := FALSE;
            Axis.Error := TRUE;
            Axis.ErrorID := 1;
            Axis.AxisState := 6;
            Axis.CommandAborted := TRUE;
            CommandAborted := TRUE;
            owned := FALSE;
        ELSIF (Velocity > 0.0 AND Axis.LimitPos) OR
              (Velocity < 0.0 AND Axis.LimitNeg) THEN
            Axis.Velocity := 0.0;
            Axis.Active := FALSE;
            Axis.InVelocity := FALSE;
            Axis.Error := TRUE;
            Axis.ErrorID := 2;
            Axis.AxisState := 6;
            Axis.CommandAborted := TRUE;
            CommandAborted := TRUE;
            owned := FALSE;
        ELSE
            IF Axis.Velocity < Velocity THEN
                Axis.Velocity := Axis.Velocity + Acceleration * 0.01;
                IF Axis.Velocity >= Velocity THEN
                    Axis.Velocity := Velocity;
                END_IF;
            ELSIF Axis.Velocity > Velocity THEN
                Axis.Velocity := Axis.Velocity - Acceleration * 0.01;
                IF Axis.Velocity <= Velocity THEN
                    Axis.Velocity := Velocity;
                END_IF;
            END_IF;

            IF Axis.Velocity = Velocity THEN
                InVelocity := TRUE;
                Axis.InVelocity := TRUE;
            ELSE
                InVelocity := FALSE;
                Axis.InVelocity := FALSE;
            END_IF;

            IF Velocity >= 0.0 THEN
                Axis.Position := Axis.Position + Axis.Velocity * 0.01;
            ELSE
                Axis.Position := Axis.Position - Axis.Velocity * 0.01;
            END_IF;
        END_IF;
    END_IF;
ELSE
    IF owned THEN
        Axis.Velocity := 0.0;
        Axis.Active := FALSE;
        Axis.AxisState := 1;
        Axis.InVelocity := FALSE;
        owned := FALSE;
    END_IF;
    InVelocity := FALSE;
END_IF;

Busy := owned;
Active := owned AND Axis.Active;

END_FUNCTION_BLOCK
