(* Virtual axis simulation model shared by all MC_* stub function blocks.
   AxisState values: 0=Disabled 1=Standstill 2=Homing 3=DiscreteMotion 4=ContinuousMotion 5=Stopping 6=ErrorStop
   ErrorID values: 1=EStop 2=LimitSwitch *)

TYPE AXIS_REF :
STRUCT
    Position        : REAL;
    Velocity        : REAL;
    TargetPosition  : REAL;
    TargetVelocity  : REAL;
    Accel           : REAL;
    Decel           : REAL;
    Direction       : INT;
    CommandId       : DINT;
    AxisState       : INT;
    Enabled         : BOOL;
    Homed           : BOOL;
    Busy            : BOOL;
    Done            : BOOL;
    Active          : BOOL;
    CommandAborted  : BOOL;
    Error           : BOOL;
    ErrorID         : DINT;
    InVelocity      : BOOL;
    EStopActive     : BOOL;
    LimitPos        : BOOL;
    LimitNeg        : BOOL;
    HomeSwitch      : BOOL;
END_STRUCT;
END_TYPE

(* Fixed simulated scan period (seconds), inlined as a literal in each FB below
   rather than a shared VAR_GLOBAL -- this matiec build rejects VAR_GLOBAL
   declared outside a CONFIGURATION/RESOURCE. Scenario assertions must be
   scan-count/state-based, never wall-clock-based, so the exact value here
   only affects how many scans a move takes, not correctness. *)
