PROGRAM MAIN
VAR
    Axis1     : AXIS_REF;
    Pwr       : MC_Power;
    Jogger    : MC_MoveVelocity;
    Rst       : MC_Reset;
    bEnable   : BOOL;
    bResetReq : BOOL;
    rJogVel   : REAL := -1500.0;
END_VAR

Pwr(Enable := bEnable, Axis := Axis1);
Rst(Execute := bResetReq, Axis := Axis1);
Jogger(Execute := bEnable, Velocity := rJogVel, Acceleration := 1000.0, Axis := Axis1);
END_PROGRAM
