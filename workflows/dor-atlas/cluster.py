import dask
import os 
import dask_jobqueue



class PerlmutterSLURMCluster:
    def __new__(cls, *args, **kwargs):
        jupyterhub_server_name = os.environ.get('JUPYTERHUB_SERVER_NAME', None)
        dashboard_link = (
                        'https://jupyter.nersc.gov/user/'
                        + '{USER}'
                        + f'/{jupyterhub_server_name}/proxy/'
                        + '{port}/status'
                    )
        dask.config.set({'distributed.dashboard.link': dashboard_link})

        cluster = dask_jobqueue.SLURMCluster(*args, **kwargs)
        return cluster
