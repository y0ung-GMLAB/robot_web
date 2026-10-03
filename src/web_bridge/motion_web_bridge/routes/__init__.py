from .project_routes import register_project_routes
from .motor_routes import register_motor_routes
from .motion_run_routes import register_motion_run_routes
from .safety_routes import register_safety_routes
from .system_routes import register_system_routes
from .schedule_routes import register_schedule_routes
from .docs_routes import register_docs_routes
from .motion_trace_routes import register_motion_trace_routes
from .stream_routes import register_stream_routes
from .robot_pack_routes import register_robot_pack_routes
from .terminal_routes import register_terminal_routes

__all__ = [
    'register_project_routes',
    'register_motor_routes',
    'register_motion_run_routes',
    'register_safety_routes',
    'register_system_routes',
    'register_schedule_routes',
    'register_docs_routes',
    'register_motion_trace_routes',
    'register_stream_routes',
    'register_robot_pack_routes',
    'register_terminal_routes',
]
