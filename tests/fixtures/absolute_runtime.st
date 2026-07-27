PROGRAM MAIN
VAR
    Axis1      : AXIS_REF;
    Pwr        : MC_Power;
    Mover      : MC_MoveAbsolute;
    Rst        : MC_Reset;
    bEnable    : BOOL;
    bResetReq  : BOOL;
    rTargetPos : REAL := 250.0;
    rVelocity  : REAL := 800.0;
END_VAR

Pwr(Enable := bEnable, Axis := Axis1);
Rst(Execute := bResetReq, Axis := Axis1);
Mover(
    Execute := bEnable,
    Position := rTargetPos,
    Velocity := rVelocity,
    Axis := Axis1
);
END_PROGRAM
