FUNCTION_BLOCK MC_MoveAbsolute
VAR_INPUT
    Execute  : BOOL;
    Position : REAL;
    Velocity : REAL;
END_VAR
VAR_OUTPUT
    Done           : BOOL;
    Busy           : BOOL;
    Active         : BOOL;
    CommandAborted : BOOL;
    Error          : BOOL;
END_VAR
VAR_IN_OUT
    Axis : AXIS_REF;
END_VAR
VAR
    execRise  : R_TRIG;
    execFall  : F_TRIG;
    myCommand : DINT;
    owned     : BOOL;
END_VAR

execRise(CLK := Execute);
execFall(CLK := Execute);

IF execRise.Q THEN
    IF NOT Axis.Enabled OR Axis.EStopActive OR Axis.AxisState = 6 THEN
        CommandAborted := TRUE;
        Error := TRUE;
    ELSIF Axis.Busy AND Axis.CommandId <> myCommand THEN
        CommandAborted := TRUE;
        Error := TRUE;
    ELSE
        Axis.CommandId := Axis.CommandId + 1;
        myCommand := Axis.CommandId;
        owned := TRUE;
        Axis.TargetPosition := Position;
        Axis.TargetVelocity := Velocity;
        Axis.Busy := TRUE;
        Axis.Active := TRUE;
        Axis.Done := FALSE;
        Axis.AxisState := 3;
        CommandAborted := FALSE;
        Error := FALSE;
    END_IF;
END_IF;

IF owned AND Axis.CommandId = myCommand THEN
    IF Axis.EStopActive THEN
        Axis.Velocity := 0.0;
        Axis.Busy := FALSE;
        Axis.Active := FALSE;
        Axis.Error := TRUE;
        Axis.ErrorID := 1;
        Axis.AxisState := 6;
        Axis.CommandAborted := TRUE;
        CommandAborted := TRUE;
        owned := FALSE;
    ELSIF (Axis.TargetPosition > Axis.Position AND Axis.LimitPos) OR
          (Axis.TargetPosition < Axis.Position AND Axis.LimitNeg) THEN
        Axis.Velocity := 0.0;
        Axis.Busy := FALSE;
        Axis.Active := FALSE;
        Axis.Error := TRUE;
        Axis.ErrorID := 2;
        Axis.AxisState := 6;
        Axis.CommandAborted := TRUE;
        CommandAborted := TRUE;
        owned := FALSE;
    ELSE
        Axis.Velocity := Axis.TargetVelocity;
        IF Axis.TargetPosition > Axis.Position THEN
            Axis.Position := Axis.Position + Axis.Velocity * 0.01;
            IF Axis.Position >= Axis.TargetPosition THEN
                Axis.Position := Axis.TargetPosition;
            END_IF;
        ELSE
            Axis.Position := Axis.Position - Axis.Velocity * 0.01;
            IF Axis.Position <= Axis.TargetPosition THEN
                Axis.Position := Axis.TargetPosition;
            END_IF;
        END_IF;

        IF Axis.Position = Axis.TargetPosition THEN
            Axis.Velocity := 0.0;
            Axis.Busy := FALSE;
            Axis.Active := FALSE;
            Axis.Done := TRUE;
            Axis.AxisState := 1;
        END_IF;
    END_IF;
END_IF;

Busy := owned AND Axis.Busy;
Active := owned AND Axis.Active;
Done := owned AND Axis.Done;

IF execFall.Q THEN
    Axis.Done := FALSE;
    owned := FALSE;
END_IF;

END_FUNCTION_BLOCK
