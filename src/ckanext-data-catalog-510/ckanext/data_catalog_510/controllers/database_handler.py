from sqlalchemy.sql.schema import Table
from ckan.common import config, _
import ckan.logic as logic

import json
from geoalchemy2 import Geometry
import geopandas as gpd
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError

import logging
log = logging.getLogger(__name__)
EXCLUDE_SCHEMAS = ['information_schema']

ValidationError = logic.ValidationError
NotFound = logic.NotFound


class SQLHandler:
    def __init__(self):
        self.db_type = ""
        self.db_uri = ""

    def get_databases(self, db_type, return_url=False):
        ''' Method is used to fetch the databases from the configuration
        the config should have the DB in the list.
        e.g [
                {
                    "name":"test",
                    "title":"Test",
                    "url":"postgresql://ckan:ckan@db/ckan"
                }
            ]
        '''
        if db_type == 'postgres':
            db_connections = config.get('ckan.postgresql_db_connections', '')
        if db_type == 'mysql':
            db_connections = config.get('ckan.mysql_db_connections', '')
        if db_type == 'azuresql':
            db_connections = config.get('ckan.azuresql_db_connections', '')
        db_connections = json.loads(db_connections)
        if db_type == 'azuresql':
            db_connections = [dict(item, **{'db_name':item['url'].split('/')[-1].split('?')[0]}) for item in db_connections]
        else:  
            db_connections = [dict(item, **{'db_name':item['url'].split('/')[-1]}) for item in db_connections]
        if not return_url:
            [db.pop('url', None) for db in db_connections]
        log.info(db_connections)
        return db_connections

    def get_db_connection_string(self, db_name):
        '''Method is used to get the url for the db from the connection
        string
        :param db_name: will be given to find the the url of db connection
        string(required).
        :type db_name: string

        :rtype: string
        '''
        db_connections = self.get_databases(self.db_type, return_url=True)
        log.info(db_name)
        filtered = [db['url'] for db in db_connections if db['db_name'] == db_name]
        if bool(filtered):
            return filtered[0]
        else:
            raise ValidationError(_('Database not available'))

    def fetch_schema(self, db_type, db_name):
        '''Method is used to get the fetch the schemas for given db
        :param db_name: will be given to find the the url of db connection
        string(required).
        :type db_name: string

        :rtype: list of schemas
        '''
        try:
            self.db_type = db_type
            log.info(db_name)
            self.db_uri = self.get_db_connection_string(db_name)
            engine = create_engine(self.db_uri)
            inspector = inspect(engine)            
            schemas = inspector.get_schema_names()
            schemas = [x for x in schemas if x not in EXCLUDE_SCHEMAS]
            if bool(schemas):
                return schemas
            else:
                raise NotFound(_('No Schema found in Database {}'
                                 .format(db_name)))
        except SQLAlchemyError as e:
            error = str(e.__dict__['orig'])
            log.error(error)
            raise ValidationError(_(error))
        except Exception as e:
            log.error(e)
            raise e

    def fetch_tables(self, db_type, db_name, schema):
        '''Method is used to get the fetch the table for given db and schema
        :param db_name: will be given to find the the url of db connection
        string(required).
        :type db_name: string
        :param schema: will be given to find the the tables the schema
        string(required).
        :type schema: string

        :rtype: list of tables
        '''
        try:
            self.db_type = db_type
            self.db_uri = self.get_db_connection_string(db_name)
            engine = create_engine(self.db_uri)
            inspector = inspect(engine)
            tables = inspector.get_table_names(schema=schema)
            if bool(tables):
                return tables
            else:
                raise NotFound(_('No Tables found in {} schema of Database {}'
                                 .format(schema, db_name)))

        except SQLAlchemyError as e:
            error = str(e.__dict__['orig'])
            log.error(error)
            raise ValidationError(_(error))
        except Exception as e:
            log.error(e)
            raise e

    def fetch_metadata(self, db_type, db_name, schema, table_name):
        '''Method is used to get the fetch the metadata of tables for given
        db and schema
        :param db_name: will be given to find the the url of db connection
        string(required).
        :type db_name: string
        :param schema: will be given to find the the tables the schema
        string(required).
        :type schema: string
        :param table_name: will be given to find the the metadata of table
        string(required).
        :type table_name: string

        :rtype: list of metadata
        '''
        try:
            self.db_type = db_type
            self.db_uri = self.get_db_connection_string(db_name)
            engine = create_engine(self.db_uri)
            if db_type == 'mysql':
                query = f'Select Count(*) from `{schema}`.{table_name};'
            else:
                query = f'Select Count(*) from {schema}.{table_name};'
            
            result = engine.execute(query)
            count = result.first()[0]
            inspector = inspect(engine)
            columns = inspector.get_columns(table_name, schema=schema)
            # log.info(columns)
            col_type_list = list(map(lambda column: column['type'], columns))
            cols_list = list(map(lambda column: column['name'], columns))
            is_geo = False
            geo_metadata = {}
            if db_type == 'postgres':
                con = engine.connect()
                for column_type in enumerate(col_type_list):
                    # log.info(str(column_type))
                    if 'Geo' in str(column_type):
                        is_geo = True
                        # log.info(cols_list[column_type[0]])
                        geoData = gpd.read_postgis(f'SELECT {cols_list[column_type[0]]} FROM {schema}.{table_name}', con=con, geom_col=cols_list[column_type[0]])
                        geo_metadata['spatial_extent'] = str(geoData.total_bounds)
                        geo_metadata['spatial_resolution'] = ''
                        geo_metadata['spatial_reference_system'] = str(geoData.crs.to_epsg() if geoData.crs else None)
                        break
            table_metadata = {
                'no_of_records': count,
                'no_of_attributes': len(cols_list),
                'is_geo': is_geo,
                'geo_metadata': geo_metadata
            }
            return table_metadata

        except SQLAlchemyError as e:
            error = str(e.__dict__['orig'])
            log.error(error)
            raise ValidationError(_(error))
        except Exception as e:
            log.error(e)
            raise e
