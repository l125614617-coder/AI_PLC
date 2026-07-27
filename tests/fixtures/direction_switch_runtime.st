PROGRAM MAIN
VAR
    Axis1       : AXIS_REF;
    Pwr         : MC_Power;
    Jogger      : MC_MoveVelocity;
    bEnable     : BOOL;
    bReverseReq : BOOL;
    rVelocity   : REAL;
END_VAR

IF bReverseReq THEN
    rVelocity := -1000.0;
ELSE
    rVelocity := 1000.0;
END_IF;
Pwr(Enable := bEnable, Axis := Axis1);
Jogger(Execute := bEnable, Velocity := rVelocity, Acceleration := 5000.0, Axis := Axis1);
END_PROGRAM
