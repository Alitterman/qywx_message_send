from qx.config import app_config
import requests
import json
import qx.error_table

# from requests_toolbelt import MultipartEncoder

"""
使用注意
- 如果有在管理端对应用设置“在微工作台中始终进入主页”，应用在微信端只能接收到文本消息，并且文本消息的长度限制为20字节，超过20字节会被截断。同时其他消息类型也会转换为文本消息，提示用户到企业微信查看。
- 支持id转译，将userid/部门id转成对应的用户名/部门名，目前仅文本/文本卡片/图文/图文（mpnews）/任务卡片/小程序通知/模版消息/模板卡片消息这八种消息类型的部分字段支持。仅第三方应用需要用到，企业自建应用可以忽略。具体支持的范围和语法，请查看附录id转译说明。
- 支持重复消息检查，当指定 "enable_duplicate_check": 1开启: 表示在一定时间间隔内，同样内容（请求json）的消息，不会重复收到；时间间隔可通过duplicate_check_interval指定，默认1800秒。
- 从2021年2月4日开始，企业关联添加的「小程序」应用，也可以发送文本、图片、视频、文件、图文等各种类型的消息了。
调用建议：大部分企业应用在每小时的0分或30分触发推送消息，容易造成资源挤占，从而投递不够及时，建议尽量避开这两个时间点进行调用。
"""


class Message:

    def __init__(self, error_table_path='error_table.py'):
        self.errors = []  # {'code':'','info':''}
        self.files = {}  # {'filename':''} 用来存储已上传文件的media_id

        self.crop_id = app_config['corp_id']
        self.agent_id = app_config['agent_id']
        self.app_secret = app_config['app_secret']
        self.access_token = self.get_access_token()

        self.post_url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}".format(
            access_token=self.access_token)

        # 将错误映射表读入
        self.error_info_table = qx.error_table.error_info_table

    def get_errors_text(self):
        info = ''
        for error in self.errors:
            info += error['info'].replace('\n', '') + ' | '

        return info[:-3]  # 返回errors里的info，多个用|隔开

    def get_errors(self):
        return self.errors

    def add_error(self, code, info=''):
        # 错误信息处理
        if info == '':
            info = code
            code = ''
        self.errors.append({'code': code, 'info': info})

    def error_handling(self, response_code):
        """
        根据错误码进行相关的处理
        """
        if response_code == 0:
            return True
        else:
            code = response_code
            info = self.error_info_table[str(code)]
            self.add_error(code, info)
            return False

    def get_access_token(self):
        response = requests.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={crop_id}&corpsecret={app_secret}".format(
                crop_id=self.crop_id, app_secret=self.app_secret))
        data = json.loads(response.text)
        res_content_dict = json.loads(response.text)
        if (self.error_handling(res_content_dict['errcode'])):
            return data['access_token']
        else:
            return False

    def get_department(self):
        get_department_url = "https://qyapi.weixin.qq.com/cgi-bin/department/list?access_token={access_token}".format(
            access_token=self.access_token)
        response = requests.get(url=get_department_url)
        res_content_dict = json.loads(response.text)
        if (self.error_handling(res_content_dict['errcode'])):
            return res_content_dict["department"]
        else:
            return False

    # 上传临时文件素材接口，图片也可使用此接口，20M上限
    def upload_file(self, filepath, _filetype='file'):
        """
        文件上传接口
        :param filepath 文件路径
        """
        upload_file_url = "https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token={access_token}&type={filetype}".format(
            access_token=self.access_token, filetype=_filetype)
        filename = self.get_filename(filepath)
        file_data = {"file": open(filepath, 'rb')}

        response = requests.post(url=upload_file_url, files=file_data, headers={'Content-Type': 'multipart/form-data'})
        res_content_dict = json.loads(response.text)
        print("upload " + res_content_dict['errmsg'])
        self.files[filename] = res_content_dict['media_id']  # 媒体文件上传后获取的唯一标识，3天内有效
        return self.error_handling(res_content_dict['errcode'])

    @staticmethod
    def get_filename(filepath):
        # 获取文件名称
        if '/' in filepath:
            filename = filepath.split('/')[-1]
        elif '\\' in filepath:
            filename = filepath.split('\\')[-1]
        else:
            filename = filepath
        return filename

    def get_fileid(self, filename):
        """
        获取文件id
        """
        if filename in self.files:
            return self.files[filename]
        else:
            return None

    # 向企业内部发送文字消息接口，_message为字符串,以下to_crop同理
    def send_text_to_crop(self, receive_sector, _message):
        """
        :param _message:信息内容
        :param receive_sector: 选择发送对象
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {
                "content": _message  # 消息内容，最长不超过2048个字节，超过将截断（支持id转译）
            },
            "safe": 0,  # 表示是否是保密消息，0表示可对外分享，1表示不能分享且内容显示水印，默认为0
            "enable_id_trans": 1,  # 表示是否开启id转译，0表示否，1表示是，默认0。仅第三方应用需要用到，企业自建应用可以忽略。
            "enable_duplicate_check": 0,  # 表示是否开启重复消息检查，0表示否，1表示是，默认0
            "duplicate_check_interval": 1800  # 表示是否重复消息检查的时间间隔，默认1800s，最大不超过4小时
        }

        json_str = json.dumps(json_dict)
        response_send = requests.post(self.post_url, data=json_str)
        print("send text to " + str(receive_sector) + ' ' + json.loads(response_send.text)['errmsg'])
        return self.error_handling(json.loads(response_send.text)['errcode'])

    def send_image_to_crop(self, receive_sector, _image_path):
        """
        :param _image_path:图片路径
        :param receive_sector: 选择发送对象
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        img_name = self.get_filename(_image_path)
        media_id = self.get_fileid(img_name)
        # 未上传过文件，进行文件上传并获取到media_id
        if media_id is None:
            if self.upload_file(_image_path, "image"):
                media_id = self.get_fileid(img_name)

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "image",
            "agentid": self.agent_id,
            "image": {
                "media_id": media_id
            },
            "safe": 0,  # 表示是否是保密消息，0表示可对外分享，1表示不能分享且内容显示水印，默认为0
            "enable_id_trans": 1,  # 表示是否开启id转译，0表示否，1表示是，默认0。仅第三方应用需要用到，企业自建应用可以忽略。
            "enable_duplicate_check": 0,  # 表示是否开启重复消息检查，0表示否，1表示是，默认0
            "duplicate_check_interval": 1800  # 表示是否重复消息检查的时间间隔，默认1800s，最大不超过4小时
        }

        json_str = json.dumps(json_dict)
        response = requests.post(self.post_url, data=json_str)

        res_content_dict = json.loads(response.text)
        # res_content_dict ={'error_code':int,'errmsg':''}
        if res_content_dict['errcode'] == 40007:
            # 超时重传，文件过期则重新上传
            self.upload_file(_image_path, "image")
            self.send_file_to_crop(_image_path, receive_sector)

        print("send image to " + str(receive_sector) + ' ' + res_content_dict['errmsg'])
        return self.error_handling(res_content_dict['errcode'])

    def send_voice_to_crop(self, receive_sector, _voice_path):
        """
        :param _voice_path: 资源路径
        :param receive_sector: 选择发送对象
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        file_name = self.get_filename(_voice_path)
        media_id = self.get_fileid(file_name)
        # 未上传过文件，进行文件上传并获取到media_id
        if media_id is None:
            if self.upload_file(_voice_path, "voice"):
                media_id = self.get_fileid(file_name)

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "voice",
            "agentid": self.agent_id,
            "voice": {
                "media_id": media_id
            },
            "enable_duplicate_check": 0,
            "duplicate_check_interval": 1800
        }

        json_str = json.dumps(json_dict)
        response = requests.post(self.post_url, data=json_str)

        res_content_dict = json.loads(response.text)
        # res_content_dict ={'error_code':int,'errmsg':''}
        if res_content_dict['errcode'] == 40007:
            # 超时重传，文件过期则重新上传
            self.upload_file(_voice_path, "voice")
            self.send_file_to_crop(_voice_path, receive_sector)

        print("send voice to " + str(receive_sector) + ' ' + res_content_dict['errmsg'])
        return self.error_handling(res_content_dict['errcode'])

    def send_video_to_crop(self, receive_sector, _video_path, title='', Description=''):
        """
        :param _video_path: 资源路径
        :param receive_sector: 选择发送对象
        :param Description: 视频描述
        :param title: 视频标题
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        file_name = self.get_filename(_video_path)
        media_id = self.get_fileid(file_name)
        # 未上传过文件，进行文件上传并获取到media_id
        if media_id is None:
            if self.upload_file(_video_path, "voice"):
                media_id = self.get_fileid(file_name)

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "video",
            "agentid": self.agent_id,
            "video": {
                "media_id": media_id,
                "title": title,
                "description": Description
            },
            "safe": 0,
            "enable_duplicate_check": 0,
            "duplicate_check_interval": 1800
        }

        json_str = json.dumps(json_dict)
        response = requests.post(self.post_url, data=json_str)

        res_content_dict = json.loads(response.text)
        # res_content_dict ={'error_code':int,'errmsg':''}
        if res_content_dict['errcode'] == 40007:
            # 超时重传，文件过期则重新上传
            self.upload_file(_video_path, "voice")
            self.send_file_to_crop(_video_path, receive_sector)

        print("send video to " + str(receive_sector) + ' ' + res_content_dict['errmsg'])
        return self.error_handling(res_content_dict['errcode'])

    def send_file_to_crop(self, receive_sector, filepath):
        """
        发送文件
        :param filepath 文件目录
        :param receive_sector: 接收对象
        """
        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        filename = self.get_filename(filepath)
        media_id = self.get_fileid(filename)
        # 未上传过文件，进行文件上传并获取到media_id
        if media_id is None:
            if self.upload_file(filepath):
                media_id = self.get_fileid(filename)

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_data = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "file",
            "file": {
                "media_id": media_id,
            },
            "safe": 0,
            "enable_duplicate_check": 0,
            "duplicate_check_interval": 1800
        }
        response = requests.post(url=self.post_url, json=json_data)

        res_content_dict = json.loads(response.text)
        # res_content_dict ={'error_code':int,'errmsg':''}
        if res_content_dict['errcode'] == 40007:
            # 超时重传，文件过期则重新上传
            self.upload_file(filepath)
            self.send_file_to_crop(filepath)
        print("send file to " + str(receive_sector) + ' ' + res_content_dict['errmsg'])
        return self.error_handling(res_content_dict['errcode'])

    def send_textcard_to_crop(self, receive_sector, title='', _description='   ', url='', btntxt='详情'):
        """
        发送信息卡片
        :param _description:信息内容
        :param title: 标题，不超过128个字节
        :param receive_sector: 选择发送对象
        :param url:点击后跳转的链接。最长2048字节，请确保包含了协议头(http/https)
        :param btntxt:按钮文字。 默认为“详情”， 不超过4个文字

        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "textcard",
            "agentid": self.agent_id,
            "textcard": {
                "title": title,
                "description": _description,
                "url": url,
                "btntxt": btntxt
            },
            "safe": 0,  # 表示是否是保密消息，0表示可对外分享，1表示不能分享且内容显示水印，默认为0
            "enable_id_trans": 1,  # 表示是否开启id转译，0表示否，1表示是，默认0。仅第三方应用需要用到，企业自建应用可以忽略。
            "enable_duplicate_check": 0,  # 表示是否开启重复消息检查，0表示否，1表示是，默认0
            "duplicate_check_interval": 1800  # 表示是否重复消息检查的时间间隔，默认1800s，最大不超过4小时
        }

        json_str = json.dumps(json_dict)
        response_send = requests.post(self.post_url, data=json_str)
        print("send textcard to " + str(receive_sector) + ' ' + json.loads(response_send.text)['errmsg'])
        return self.error_handling(json.loads(response_send.text)['errcode'])

    def send_news_to_crop(self, receive_sector, _news):
        """
        发送图文信息
        :param _news:信息内容
        :param receive_sector: 选择发送对象
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "news",
            "agentid": self.agent_id,
            "news": _news,
            "enable_id_trans": 0,  # 表示是否开启id转译，0表示否，1表示是，默认0。仅第三方应用需要用到，企业自建应用可以忽略。
            "enable_duplicate_check": 0,  # 表示是否开启重复消息检查，0表示否，1表示是，默认0
            "duplicate_check_interval": 1800  # 表示是否重复消息检查的时间间隔，默认1800s，最大不超过4小时
        }

        json_str = json.dumps(json_dict)
        response_send = requests.post(self.post_url, data=json_str)
        print("send news to " + str(receive_sector) + ' ' + json.loads(response_send.text)['errmsg'])
        return self.error_handling(json.loads(response_send.text)['errcode'])

    def send_markdown_to_crop(self, receive_sector, _content):
        """
        :param _content:信息内容
        :param receive_sector: 选择发送对象
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "markdown",
            "agentid": self.agent_id,
            "markdown": {
                "content": _content
            },
            "enable_duplicate_check": 0,  # 表示是否开启重复消息检查，0表示否，1表示是，默认0
            "duplicate_check_interval": 1800  # 表示是否重复消息检查的时间间隔，默认1800s，最大不超过4小时
        }

        json_str = json.dumps(json_dict)
        response_send = requests.post(self.post_url, data=json_str)
        print("send markdown to " + str(receive_sector) + ' ' + json.loads(response_send.text)['errmsg'])
        return self.error_handling(json.loads(response_send.text)['errcode'])

    def send_template_card_to_crop(self, receive_sector, _template_card):
        """
        发送模板信息
        :param _template_card:信息内容 信息格式详情见文档 https://developer.work.weixin.qq.com/document/path/90236#%E6%A8%A1%E6%9D%BF%E5%8D%A1%E7%89%87%E6%B6%88%E6%81%AF
        :param receive_sector: 选择发送对象
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        user_id_str = "|".join(receive_sector.setdefault("touser", []))  # userid 在企业微信-通讯录-成员-账号
        party_id_str = "|".join(receive_sector.setdefault("toparty", []))  # 部门id
        tag_id_str = "|".join(receive_sector.setdefault("totag", []))  # 标签名称
        json_dict = {
            "touser": user_id_str,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_str,
            "totag": tag_id_str,
            "msgtype": "template_card",
            "agentid": self.agent_id,
            "template_card": _template_card,
            "enable_id_trans": 0,  # 表示是否开启id转译，0表示否，1表示是，默认0。仅第三方应用需要用到，企业自建应用可以忽略。
            "enable_duplicate_check": 0,  # 表示是否开启重复消息检查，0表示否，1表示是，默认0
            "duplicate_check_interval": 1800  # 表示是否重复消息检查的时间间隔，默认1800s，最大不超过4小时
        }

        json_str = json.dumps(json_dict)
        response_send = requests.post(self.post_url, data=json_str)
        print("send template_card to " + str(receive_sector) + ' ' + json.loads(response_send.text)['errmsg'])
        return self.error_handling(json.loads(response_send.text)['errcode'])

    # 向关联企业发送文字消息接口，_message为字符串，以下to_linkedcorp同理
    def send_text_to_linkedcorp(self, receive_sector, _message):
        """
        :param _message:信息内容
        :param receive_sector: 选择发送对象
            {
            "type": '',
                #可选参数，-1 错误输入， 1 接收对象为指定成员，2 接收对象为指定部门，3 接受对象为指定标签
            "user_id_list": ['name1|name2']
            }
        请求实例看__main__函数
        """

        # 错误输入，报错
        if not isinstance(receive_sector, dict):
            return False

        user_id_list = receive_sector.setdefault("touser", [])  # userid 在企业微信-通讯录-成员-账号
        party_id_list = receive_sector.setdefault("toparty", [])  # 部门id
        tag_id_list = receive_sector.setdefault("totag", [])  # 标签名称
        json_dict = {
            "touser": user_id_list,  # 可以指定为@all,即向企业应用的全部成员发送
            "toparty": party_id_list,
            "totag": tag_id_list,
            "toall": 0,  # 1表示发送给应用可见范围内的所有人（包括互联企业的成员），默认为0
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {
                "content": _message  # 消息内容，最长不超过2048个字节，超过将截断（支持id转译）
            },
            "safe": 0,  # 表示是否是保密消息，0表示可对外分享，1表示不能分享且内容显示水印，默认为0
        }

        json_str = json.dumps(json_dict)
        response_send = requests.post(self.post_url, data=json_str)
        print("send to " + str(receive_sector) + ' ' + json.loads(response_send.text)['errmsg'])
        return self.error_handling(json.loads(response_send.text)['errcode'])


if __name__ == '__main__':
    qy = Message()
    sent_dict_example = {
        "touser": ["userid1", "userid2", "CorpId1/userid1", "CorpId2/userid2"],
        "toparty": ["partyid1", "partyid2", "LinkedId1/partyid1", "LinkedId2/partyid2"],
        "totag": ["tagid1", "tagid2"]
    }
    sent_dict = {
        "touser": ["renguangyuan"],
    }
    img_path = r"C:\Users\Administrator\Desktop\8415.png"
    fpath = r'C:\Users\Administrator\Desktop\test.txt'
    # 图文类型
    data = {
        "articles": [
            {
                "title": "news_test",
                "description": "news_test",
                "url": "www.qq.com",
                "picurl": "https://gimg2.baidu.com/image_search/src=http%3A%2F%2Ffile1.renrendoc.com%2Ffileroot_temp2%2F2020-6%2F27%2Fb5ed4aba-85cb-4328-b61f-8ffb5822678a%2Fb5ed4aba-85cb-4328-b61f-8ffb5822678a1.gif&refer=http%3A%2F%2Ffile1.renrendoc.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1668221692&t=6eb15e9c77a51a4334ea21111bf5e1d8"
            }
        ]
    }

    # 文本消息请求示例
    qy.send_text_to_crop(sent_dict, 'hello world')

    qy.send_image_to_crop(sent_dict, img_path)

    qy.send_file_to_crop(sent_dict, fpath)
    qy.send_textcard_to_crop(sent_dict, "领奖通知"
                                        "<div class=\"gray\">2016年9月26日</div> <div class=\"normal\">恭喜你抽中iPhone 7一台，领奖码：xxxx</div><div class=\"highlight\">请于2016年10月10日前联系行政同事领取</div>", )
    qy.send_news_to_crop(sent_dict, data)
    # sendTemplateCard测试
    tem = {
        "card_type": "news_notice",  # 必填
        "source": {
            "icon_url": "https://wework.qpic.cn/wwpic/252813_jOfDHtcISzuodLa_1629280209/0",
            "desc": "企业微信",
            "desc_color": 0
        },
        "main_title": {  # 必填
            "title": "欢迎使用企业微信",
            "desc": "您的好友正在邀请您加入企业微信"
        },
        "card_image": {
            "url": "https://wework.qpic.cn/wwpic/354393_4zpkKXd7SrGMvfg_1629280616/0",
            "aspect_ratio": 2.25
        },
        "image_text_area": {
            "type": 1,
            "url": "https://work.weixin.qq.com",
            "title": "欢迎使用企业微信",
            "desc": "您的好友正在邀请您加入企业微信",
            "image_url": "https://wework.qpic.cn/wwpic/354393_4zpkKXd7SrGMvfg_1629280616/0"
        },
        "quote_area": {
        },
        "vertical_content_list": [
            {
                "title": "惊喜红包等你来拿",
                "desc": "下载企业微信还能抢红包！"
            }
        ],
        "horizontal_content_list": [  # 必填
            {
                "keyname": "邀请人",
                "value": "张三"
            },
            {
                "keyname": "企微官网",
                "value": "点击访问",
                "type": 1,
                "url": "https://work.weixin.qq.com/?from=openApi"
            },
            {
                "keyname": "企微下载",
                "value": "企业微信.apk",
                "type": 2,
                "media_id": qy.get_fileid(qy.get_filename(fpath))
            }
        ],
        "jump_list": [  # 必填

        ],
        "card_action": {  # 必填
            "type": 1,  # 必填
            "url": "https://work.weixin.qq.com/?from=openApi"
        }
    }
    qy.send_markdown_to_crop(sent_dict, "### **test** \n  [这是一个空连接](https://)\n  `print('hello')` \n ")

    qy.send_template_card_to_crop(sent_dict, tem)

    # # 发送图片消息, 需先上传至临时素材
    # media_id = qy.post_file('/root/', 'a.jpg')
    # qy.send_img(media_id, ['ZhangSan'])

    # 文本消息请求示例：
    text = {
        "touser": "UserID1|UserID2|UserID3",
        "toparty": "PartyID1|PartyID2",
        "totag": "TagID1 | TagID2",
        "msgtype": "text",
        "agentid": 1,
        "text": {
            "content": "你的快递已到，请携带工卡前往邮件中心领取。\n出发前可查看<a href=\"https://work.weixin.qq.com\">邮件中心视频实况</a>，聪明避开排队。"
        },
        "safe": 0,
        "enable_id_trans": 0,
        "enable_duplicate_check": 0,
        "duplicate_check_interval": 1800
    }
    """
    参数     是否必须     说明
    touser	否	        指定接收消息的成员，成员ID列表（多个接收者用‘|’分隔，最多支持1000个）。特殊情况：指定为"@all"，则向该企业应用的全部成员发送
    toparty	否	        指定接收消息的部门，部门ID列表，多个接收者用‘|’分隔，最多支持100个。当touser为"@all"时忽略本参数
    totag	否	        指定接收消息的标签，标签ID列表，多个接收者用‘|’分隔，最多支持100个。当touser为"@all"时忽略本参数
    msgtype	是	        消息类型，此时固定为：text
    agentid	是	        企业应用的id，整型。企业内部开发，可在应用的设置页面查看；第三方服务商，可通过接口 获取企业授权信息 获取该参数值
    content	是	        消息内容，最长不超过2048个字节，超过将截断（支持id转译）
    safe	否	        表示是否是保密消息，0表示可对外分享，1表示不能分享且内容显示水印，默认为0
    enable_id_trans	            否	表示是否开启id转译，0表示否，1表示是，默认0。仅第三方应用需要用到，企业自建应用可以忽略。
    enable_duplicate_check	    否	表示是否开启重复消息检查，0表示否，1表示是，默认0
    duplicate_check_interval	否	表示是否重复消息检查的时间间隔，默认1800s，最大不超过4小时
    """
