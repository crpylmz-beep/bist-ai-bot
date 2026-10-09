"""Safe schema diagnostics: fixed codes only, never DSNs or exception messages."""
import re
import logging


def postgres_details(error):
    state=getattr(error,'sqlstate',None)
    classes={'00','01','02','03','08','09','0A','0B','0F','0L','0P','0Z',
             '20','21','22','23','24','25','26','27','28','2B','2D','2F',
             '34','38','39','3B','3D','3F','40','42','44','53','54','55',
             '57','58','72','F0','HV','P0','XX'}
    if not isinstance(state,str) or not re.fullmatch(r'[0-9A-Z]{5}',state) or state[:2] not in classes:state=None
    reasons={'28P01':'POSTGRES_AUTH_FAILED','28000':'POSTGRES_AUTH_FAILED',
             '42501':'POSTGRES_PERMISSION_DENIED','3D000':'POSTGRES_DATABASE_NOT_FOUND',
             '42601':'POSTGRES_SQL_SYNTAX','42P07':'POSTGRES_OBJECT_CONFLICT',
             '53100':'POSTGRES_DISK_FULL','53300':'POSTGRES_CONNECTION_LIMIT',
             '57P03':'POSTGRES_NOT_READY'}
    reason=reasons.get(state,'POSTGRES_OPERATION_FAILED')
    if state and state.startswith('08'):reason='POSTGRES_CONNECTION_FAILED'
    if not state:
        name=type(error).__name__
        if name in ('PoolTimeout','TimeoutError'):reason='POSTGRES_CONNECTION_TIMEOUT'
        elif name in ('OperationalError','InterfaceError','ConnectionError'):reason='POSTGRES_CONNECTION_FAILED'
    result={'reason':reason}
    if state:result['sqlstate']=state
    return result


class PoolDiagnosticsFilter(logging.Filter):
    """Capture fixed error metadata while suppressing raw pool connection messages."""
    def __init__(self):
        super().__init__();self.details=[]

    def filter(self,record):
        arguments=record.args.values() if isinstance(record.args,dict) else record.args if isinstance(record.args,tuple) else ()
        for argument in arguments:
            if isinstance(argument,BaseException):
                detail=postgres_details(argument)
                if len(self.details)<8:self.details.append(detail)
        return False

    def best(self):
        return next((detail for detail in self.details if detail.get('sqlstate')),None)
