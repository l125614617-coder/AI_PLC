(* 
   FUNCTION_BLOCK MotionControl_Safe
   Description: Safe motion control with E-stop, limits, and reset logic.
*)
FUNCTION_BLOCK MotionControl_Safe
VAR_INPUT
    bEnable          : BOOL;           (* Enable flag *)
    bEStop           : BOOL;           (* Emergency Stop Input *)
    nTargetPos       : INT;            (* Target Position in mm (Absolute) *)
    vMaxSpeed        : REAL;           (* Max Speed limit in rpm *)
    pLimitSwitch     : ARRAY[0..1] OF BOOL; (* Limit switches: 0=Min, 1=Max *)
END_VAR

VAR_OUTPUT
    bRunning         : BOOL;           (* Is motor running? *)
    nActualPos       : INT;            (* Current Position *)
    eStatus          : STRING;         (* Status Text *)
END_VAR

VAR
    vCurrentSpeed    : REAL := 0.0;   (* Internal speed variable *)
    bAtLimitMin      : BOOL;           (* Min limit detected *)
    bAtLimitMax      : BOOL;           (* Max limit detected *)
    bSafeToMove      : BOOL;           (* Safety interlock flag *)
END_VAR

(* --- 1. Emergency Stop & Enable Logic (Safety Priority) --- *)
IF bEStop THEN
    bEnable := FALSE;                  (* Force disable on E-Stop trigger *)
    eStatus := 'EMERGENCY_STOP';
ELSIF NOT bEnable THEN
    vCurrentSpeed := 0.0;              (* Ramp down or hold at zero if disabled *)
    nActualPos := INT(vCurrentSpeed); (* Update position display (simplified) *)
    bRunning := FALSE;
    eStatus := 'DISABLED';
END_IF

(* --- 2. Safety Interlocks & Limit Switch Logic --- *)
bSafeToMove := TRUE;                  (* Default safe state if E-Stop is not active *)

IF pLimitSwitch[0] THEN               (* Check Min Limit */
    bAtLimitMin := TRUE;
    vCurrentSpeed := -vMaxSpeed * 1.2;(* Overshoot protection: rapid stop/reverse logic placeholder *)
END_IF;

IF pLimitSwitch[1] THEN               (* Check Max Limit *)
    bAtLimitMax := TRUE;
    vCurrentSpeed := vMaxSpeed * 1.2; 
END_IF;

bSafeToMove := NOT (bAtLimitMin OR bAtLimitMax);(* Disable movement if at limits *)

IF bEStop THEN
    bRunning := FALSE;                (* Ensure stop command is executed *)
ELSE IF bEnable AND bSafeToMove THEN
    (* --- 3. Motion Execution Logic --- *)
    
    (* Direction logic: Forward implies increasing position for Absolute mode *)
    CASE 'forward' OF
        WHEN 'forward': 
            vCurrentSpeed := (nActualPos - nTargetPos) * 0.5; (* Simple PID-like error correction placeholder *)
            
            IF ABS(vCurrentSpeed) > vMaxSpeed THEN
                vCurrentSpeed := SIGN(nTargetPos - nActualPos) * vMaxSpeed; (* Clamp speed to max limit *)
            END_IF;
    CASE 'reverse' OF
        WHEN 'reverse': 
             vCurrentSpeed := -(nActualPos - nTargetPos) * 0.5;
             
             IF ABS(vCurrentSpeed) > vMaxSpeed THEN
                 vCurrentSpeed := SIGN(nActualPos - nTargetPos) * vMaxSpeed; (* Clamp speed *)
             END_IF;
    CASE 'stop' OF
        WHEN 'stop': 
            vCurrentSpeed := 0.0;
    ELSE
        vCurrentSpeed := 0.0;          (* Default to stop if direction unknown *)
    ENDCASE
    
    bRunning := (ABS(vCurrentSpeed) > 1.0); (* Consider running only if speed is non-zero *)

ELSE
    (* Safety or Limit triggered: Ramp down logic placeholder *)
    vCurrentSpeed := -SIGN(vCurrentSpeed) * 50; (* Decelerate rapidly but safely *)
END_IF;

(* --- 4. Update Position (Simulation of integration) --- *)
nActualPos := nActualPos + INT(ABS(vCurrentSpeed)); 
IF bAtLimitMin THEN nActualPos := MAX(nActualPos, -100); END_IF; (* Prevent underflow simulation *)
IF bAtLimitMax THEN nActualPos := MIN(nActualPos, 2000); END_IF; (* Prevent overflow simulation *)

(* Update Status Text for Debugging/Monitoring *)
eStatus := 'RUNNING';
IF NOT bRunning AND vCurrentSpeed = 0.0 THEN eStatus := 'IDLE'; END_IF;
IF bAtLimitMin OR bAtLimitMax THEN eStatus := 'LIMIT_REACHED'; END_IF;

END_FUNCTION_BLOCK